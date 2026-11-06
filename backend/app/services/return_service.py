"""Customer returns: open -> completed (inspected) or cancelled.

1. A return is opened for some shipped units of a delivered order, with a reason. A line
   can never be returned more often than it was shipped (counting other open returns).
2. When the goods arrive they are inspected line by line:
   - restock: back into sellable stock,
   - damaged: into stock as damaged units (written off or repaired later through the
     normal adjustment approval),
   into a bin of the returns zone (or a bin chosen by the inspector). Every line writes
   a RETURN movement referencing the return.
3. The order lines' returned quantities go up and the order becomes `returned`.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.catalog import Product
from app.models.inventory import ReferenceType
from app.models.order import (
    Order,
    OrderStatus,
    Return,
    ReturnCondition,
    ReturnItem,
    ReturnStatus,
)
from app.models.user import User
from app.models.warehouse import Bin, Rack, Shelf, Zone, ZoneType
from app.schemas.fulfillment import ReturnCreate, ReturnInspection
from app.services.audit_service import AuditService
from app.services.inventory_service import CapacityExceededError, InventoryService
from app.services.order_service import OrderService

logger = get_logger(__name__)

RETURNABLE = (OrderStatus.DELIVERED.value, OrderStatus.RETURNED.value)


class ReturnNotFoundError(NotFoundError):
    message = "Return not found"


class ReturnService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.orders = OrderService(db)
        self.inventory = InventoryService(db)
        self.audit = AuditService(db)

    def get(self, return_id: int) -> Return:
        found = self.db.get(Return, return_id)
        if found is None:
            raise ReturnNotFoundError()
        return found

    def for_order(self, order_id: int) -> Sequence[Return]:
        return self.db.scalars(
            select(Return).where(Return.order_id == order_id).order_by(Return.id)
        ).all()

    # ------------------------------------------------------------------- open
    def open(self, order_id: int, data: ReturnCreate, *, user: User | None) -> Return:
        order = self.orders.get(order_id)
        if order.status not in RETURNABLE:
            raise ConflictError(
                f"Order {order.order_number} is {order.status.replace('_', ' ')}; only "
                "delivered orders can be returned"
            )
        lines = {item.product_id: item for item in order.items}
        pending = self._open_quantities(order)
        items = []
        for line in data.items:
            item = lines.get(line.product_id)
            if item is None:
                raise UnprocessableError(f"Product {line.product_id} is not part of this order")
            returnable = item.quantity_shipped - item.quantity_returned - pending.get(item.id, 0)
            if line.quantity > returnable:
                raise UnprocessableError(
                    f"{item.product.sku}: only {returnable} unit(s) can still be returned"
                )
            items.append(ReturnItem(order_item_id=item.id, quantity=line.quantity))

        ret = Return(
            return_number=self._next_number(),
            order_id=order.id,
            status=ReturnStatus.OPEN,
            reason=data.reason,
            created_by_id=user.id if user else None,
        )
        ret.items = items
        self.db.add(ret)
        self.db.flush()
        self.audit.record(
            "return.open",
            "return",
            ret.id,
            summary=(
                f"Return {ret.return_number} for order {order.order_number}: "
                f"{sum(i.quantity for i in items)} unit(s) ({data.reason})"
            ),
            actor=user,
        )
        self.db.commit()
        return ret

    # ---------------------------------------------------------------- inspect
    def inspect(self, return_id: int, data: ReturnInspection, *, user: User) -> Return:
        """Receive and inspect the returned goods; every line must be inspected."""
        ret = self.get(return_id)
        if ret.status != ReturnStatus.OPEN:
            raise ConflictError(f"Return {ret.return_number} is already {ret.status}")
        order = ret.order
        by_product = {item.order_item.product_id: item for item in ret.items}
        inspected = {line.product_id: line for line in data.items}
        missing = [i.order_item.product.sku for p, i in by_product.items() if p not in inspected]
        unknown = [str(p) for p in inspected if p not in by_product]
        if missing or unknown:
            raise UnprocessableError(
                "Inspect exactly the returned lines"
                + (f"; missing: {', '.join(missing)}" if missing else "")
                + (f"; not in this return: {', '.join(unknown)}" if unknown else "")
            )
        try:
            for product_id, item in by_product.items():
                line = inspected[product_id]
                product = item.order_item.product
                bin_ = self._target_bin(line.bin_id, order, product, item.quantity)
                damaged = line.condition == ReturnCondition.DAMAGED
                self.inventory.receive_return(
                    product,
                    bin_,
                    item.quantity,
                    damaged=damaged,
                    reference=(ReferenceType.RETURN, ret.id),
                    reason=f"Return {ret.return_number}: {ret.reason}",
                    user=user,
                )
                item.condition = line.condition
                item.bin = bin_
                item.note = line.note
                item.order_item.quantity_returned += item.quantity
            ret.status = ReturnStatus.COMPLETED
            ret.inspected_by = user
            ret.completed_at = datetime.now(UTC)
            returned = sum(i.quantity_returned for i in order.items)
            shipped = sum(i.quantity_shipped for i in order.items)
            note = f"Return {ret.return_number}: {returned} of {shipped} unit(s) returned"
            if order.status == OrderStatus.DELIVERED:  # later returns: audit record only
                self.orders.transition(order, OrderStatus.RETURNED, user=user, note=note)
            self.audit.record(
                "return.complete",
                "return",
                ret.id,
                summary=note
                + " ("
                + ", ".join(
                    f"{i.quantity} x {i.order_item.product.sku} {i.condition}" for i in ret.items
                )
                + ")",
                actor=user,
            )
        except Exception:
            self.db.rollback()
            raise
        self.inventory.commit()  # also fills backorders with restocked units
        return ret

    def cancel(self, return_id: int, *, user: User | None) -> Return:
        ret = self.get(return_id)
        if ret.status != ReturnStatus.OPEN:
            raise ConflictError(f"Return {ret.return_number} is already {ret.status}")
        ret.status = ReturnStatus.CANCELLED
        self.audit.record(
            "return.cancel",
            "return",
            ret.id,
            summary=f"Return {ret.return_number} cancelled",
            actor=user,
        )
        self.db.commit()
        return ret

    # --------------------------------------------------------------- helpers
    def _open_quantities(self, order: Order) -> dict[int, int]:
        """Units per order line already announced in other open returns."""
        rows = self.db.execute(
            select(ReturnItem.order_item_id, func.sum(ReturnItem.quantity))
            .join(Return, ReturnItem.return_id == Return.id)
            .where(Return.order_id == order.id, Return.status == ReturnStatus.OPEN.value)
            .group_by(ReturnItem.order_item_id)
        ).all()
        return {item_id: int(total) for item_id, total in rows}

    def _target_bin(self, bin_id: int | None, order: Order, product: Product, quantity: int) -> Bin:
        """The chosen bin, or the first bin of the order warehouse's returns zone with room."""
        if bin_id is not None:
            return self.inventory.get_bin(bin_id)
        candidates = self.db.scalars(
            select(Bin)
            .join(Shelf, Bin.shelf_id == Shelf.id)
            .join(Rack, Shelf.rack_id == Rack.id)
            .join(Zone, Rack.zone_id == Zone.id)
            .where(
                Zone.zone_type == ZoneType.RETURNS.value,
                Zone.warehouse_id == order.warehouse_id,
                Bin.is_active.is_(True),
            )
            .order_by(Bin.location_code)
        ).all()
        for bin_ in candidates:
            try:
                self.inventory.check_fits(product, bin_, quantity, ignore_archived_product=True)
            except CapacityExceededError:
                continue
            return bin_
        raise UnprocessableError(
            f"No returns-zone bin with room for {quantity} x {product.sku}; choose a bin"
        )

    def _next_number(self) -> str:
        """RT-<year>-<6-digit sequence>, e.g. RT-2026-000007."""
        prefix = f"RT-{datetime.now(UTC).year}-"
        last = self.db.scalar(
            select(func.max(Return.return_number)).where(Return.return_number.like(f"{prefix}%"))
        )
        sequence = int(last.removeprefix(prefix)) + 1 if last else 1
        return f"{prefix}{sequence:06d}"
