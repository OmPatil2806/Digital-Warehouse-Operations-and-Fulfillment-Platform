"""Supplier purchase orders: draft -> ordered -> (partially) received, or cancelled.

1. A manager drafts a PO for one supplier and one warehouse. The unit cost of a line
   defaults to the supplier's offer for the product, else the product's purchase cost;
   the expected date defaults to today + the longest lead time of its products.
2. Ordering sends it to the supplier (in this project: just the status change).
3. Goods are received line by line into bins of the PO's warehouse (capacity checked,
   never more than was ordered). Each receipt is a normal stock receipt with the PO
   number in the movement reason, so backorders waiting for the product are filled and
   low-stock alerts resolve in the same transaction.
4. A PO still waiting for goods after its expected date raises an "overdue supplier"
   alert (`check_overdue`); full receipt or cancellation resolves it.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.audit import AlertSeverity, AlertType
from app.models.catalog import Supplier, SupplierProduct
from app.models.purchase import (
    OPEN_PO_STATUSES,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
)
from app.models.user import User
from app.models.warehouse import Warehouse
from app.schemas.purchase import PurchaseOrderCreate, PurchaseOrderReceipt
from app.services.alert_service import AlertService
from app.services.audit_service import AuditService
from app.services.inventory_service import InventoryService

logger = get_logger(__name__)

AUDIT_ENTITY = "purchase_order"


class PurchaseOrderNotFoundError(NotFoundError):
    message = "Purchase order not found"


def overdue_key(po_id: int) -> str:
    return f"{AlertType.OVERDUE_SUPPLIER.value}:po:{po_id}"


class PurchaseOrderService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.inventory = InventoryService(db)
        self.alerts = AlertService(db)
        self.audit = AuditService(db)

    # ------------------------------------------------------------------- read
    def get(self, po_id: int) -> PurchaseOrder:
        po = self.db.get(PurchaseOrder, po_id)
        if po is None:
            raise PurchaseOrderNotFoundError()
        return po

    def search(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        supplier_id: int | None = None,
        q: str | None = None,
        overdue: bool = False,
    ) -> tuple[Sequence[PurchaseOrder], int]:
        query = select(PurchaseOrder)
        if status:
            query = query.where(PurchaseOrder.status == status)
        if supplier_id is not None:
            query = query.where(PurchaseOrder.supplier_id == supplier_id)
        if q:
            pattern = f"%{q.strip()}%"
            query = query.join(Supplier, PurchaseOrder.supplier_id == Supplier.id).where(
                or_(PurchaseOrder.po_number.ilike(pattern), Supplier.name.ilike(pattern))
            )
        if overdue:
            query = query.where(
                PurchaseOrder.status.in_(OPEN_PO_STATUSES),
                PurchaseOrder.expected_date < datetime.now(UTC).date(),
            )
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = self.db.scalars(
            query.order_by(PurchaseOrder.id.desc()).offset(offset).limit(limit)
        ).all()
        return items, total

    # ----------------------------------------------------------------- create
    def create(self, data: PurchaseOrderCreate, *, user: User | None) -> PurchaseOrder:
        supplier = self.db.get(Supplier, data.supplier_id)
        if supplier is None:
            raise UnprocessableError("Supplier not found")
        if not supplier.is_active:
            raise UnprocessableError(f"Supplier {supplier.code} is archived")
        warehouse = self.db.get(Warehouse, data.warehouse_id)
        if warehouse is None or not warehouse.is_active:
            raise UnprocessableError("Warehouse not found or archived")

        offers = {
            offer.product_id: offer
            for offer in self.db.scalars(
                select(SupplierProduct).where(SupplierProduct.supplier_id == supplier.id)
            )
        }
        items = []
        lead_time = supplier.lead_time_days
        for line in data.items:
            product = self.inventory.get_product(line.product_id)
            offer = offers.get(product.id)
            if offer is not None:
                lead_time = max(lead_time, offer.effective_lead_time_days)
                if line.quantity < offer.min_order_qty:
                    raise UnprocessableError(
                        f"{product.sku}: {supplier.code} delivers at least "
                        f"{offer.min_order_qty} unit(s)"
                    )
            unit_cost = line.unit_cost
            if unit_cost is None:
                unit_cost = offer.unit_cost if offer is not None else product.unit_cost
            items.append(
                PurchaseOrderItem(product=product, quantity=line.quantity, unit_cost=unit_cost)
            )

        today = datetime.now(UTC).date()
        expected = data.expected_date or today + timedelta(days=lead_time)
        if expected < today:
            raise UnprocessableError("The expected date cannot be in the past")
        po = PurchaseOrder(
            po_number=self._next_number(),
            supplier=supplier,
            warehouse=warehouse,
            status=PurchaseOrderStatus.DRAFT,
            expected_date=expected,
            notes=data.notes,
            created_by=user,
        )
        po.items = items
        self.db.add(po)
        self.db.flush()
        self.audit.record(
            "purchase_order.create",
            AUDIT_ENTITY,
            po.id,
            summary=(
                f"Purchase order {po.po_number} drafted for {supplier.name}: "
                f"{len(items)} line(s), {po.total_cost} total"
            ),
            actor=user,
        )
        self.db.commit()
        return po

    # ----------------------------------------------------------------- status
    def order(self, po_id: int, *, user: User | None) -> PurchaseOrder:
        po = self.get(po_id)
        self._require(po, PurchaseOrderStatus.DRAFT, "ordered")
        po.status = PurchaseOrderStatus.ORDERED
        po.ordered_at = datetime.now(UTC)
        self.audit.record(
            "purchase_order.order",
            AUDIT_ENTITY,
            po.id,
            summary=f"Purchase order {po.po_number} sent to {po.supplier.name}, "
            f"expected {po.expected_date.isoformat()}",
            actor=user,
        )
        self.db.commit()
        return po

    def cancel(self, po_id: int, *, user: User | None) -> PurchaseOrder:
        po = self.get(po_id)
        if po.status not in (PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.ORDERED):
            raise ConflictError(
                f"Purchase order {po.po_number} is {po.status.replace('_', ' ')}; only draft "
                "or ordered purchase orders without received goods can be cancelled"
            )
        po.status = PurchaseOrderStatus.CANCELLED
        self.alerts.resolve_cause(overdue_key(po.id))
        self.audit.record(
            "purchase_order.cancel",
            AUDIT_ENTITY,
            po.id,
            summary=f"Purchase order {po.po_number} cancelled",
            actor=user,
        )
        self.db.commit()
        return po

    # ---------------------------------------------------------------- receive
    def receive(
        self, po_id: int, data: PurchaseOrderReceipt, *, user: User | None
    ) -> PurchaseOrder:
        """Put arrived goods into bins; all lines of one call succeed or none."""
        po = self.get(po_id)
        if po.status not in OPEN_PO_STATUSES:
            raise ConflictError(
                f"Purchase order {po.po_number} is {po.status.replace('_', ' ')}; "
                "only ordered goods can be received"
            )
        lines = {item.product_id: item for item in po.items}
        received: dict[int, int] = {}
        for line in data.items:
            item = lines.get(line.product_id)
            if item is None:
                raise UnprocessableError(f"Product {line.product_id} is not part of {po.po_number}")
            received[item.product_id] = received.get(item.product_id, 0) + line.quantity
            if received[item.product_id] > item.quantity_outstanding:
                raise UnprocessableError(
                    f"{item.product.sku}: only {item.quantity_outstanding} unit(s) are "
                    "still outstanding"
                )
        try:
            for line in data.items:
                item = lines[line.product_id]
                bin_ = self.inventory.get_bin(line.bin_id)
                if bin_.shelf.rack.zone.warehouse_id != po.warehouse_id:
                    raise UnprocessableError(
                        f"Bin {bin_.location_code} is not in warehouse {po.warehouse.code}"
                    )
                self.inventory.receive_into(
                    item.product,
                    bin_,
                    line.quantity,
                    reason=f"Purchase order {po.po_number} ({po.supplier.code})",
                    user=user,
                    audit_summary=(
                        f"Received {line.quantity} x {item.product.sku} into "
                        f"{bin_.location_code} for {po.po_number}"
                    ),
                )
                item.quantity_received += line.quantity
            complete = all(i.quantity_outstanding == 0 for i in po.items)
            po.status = (
                PurchaseOrderStatus.RECEIVED if complete else PurchaseOrderStatus.PARTIALLY_RECEIVED
            )
            if complete:
                po.received_at = datetime.now(UTC)
                self.alerts.resolve_cause(overdue_key(po.id))
            got = sum(i.quantity_received for i in po.items)
            ordered = sum(i.quantity for i in po.items)
            self.audit.record(
                "purchase_order.receive",
                AUDIT_ENTITY,
                po.id,
                summary=f"Purchase order {po.po_number}: {got} of {ordered} unit(s) received",
                actor=user,
            )
        except Exception:
            self.db.rollback()
            raise
        self.inventory.commit()  # fills backorders and updates stock alerts too
        logger.info("Received goods for %s (%s)", po.po_number, po.status)
        return po

    # ---------------------------------------------------------------- overdue
    def check_overdue(self, *, today: date | None = None) -> list[PurchaseOrder]:
        """Raise (or refresh) an alert for every PO waiting past its expected date."""
        today = today or datetime.now(UTC).date()
        late = self.db.scalars(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.status.in_(OPEN_PO_STATUSES),
                PurchaseOrder.expected_date < today,
            )
            .order_by(PurchaseOrder.expected_date, PurchaseOrder.id)
        ).all()
        for po in late:
            days = (today - po.expected_date).days
            outstanding = sum(i.quantity_outstanding for i in po.items)
            self.alerts.raise_alert(
                AlertType.OVERDUE_SUPPLIER,
                overdue_key(po.id),
                severity=AlertSeverity.CRITICAL if days > 7 else AlertSeverity.WARNING,
                title=f"Overdue delivery: {po.po_number}",
                message=(
                    f"{po.supplier.name} is {days} day(s) late with {outstanding} unit(s) "
                    f"for {po.warehouse.code} (expected {po.expected_date.isoformat()})."
                ),
            )
        self.db.commit()
        if late:
            logger.info("%s purchase order(s) overdue", len(late))
        return list(late)

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _require(po: PurchaseOrder, status: PurchaseOrderStatus, action: str) -> None:
        if po.status != status:
            raise ConflictError(
                f"Purchase order {po.po_number} is {po.status.replace('_', ' ')}; "
                f"only {status.value} purchase orders can be {action}"
            )

    def _next_number(self) -> str:
        """PO-<year>-<6-digit sequence>, e.g. PO-2026-000003."""
        prefix = f"PO-{datetime.now(UTC).year}-"
        last = self.db.scalar(
            select(func.max(PurchaseOrder.po_number)).where(
                PurchaseOrder.po_number.like(f"{prefix}%")
            )
        )
        sequence = int(last.removeprefix(prefix)) + 1 if last else 1
        return f"{prefix}{sequence:06d}"
