"""Orders: creation, confirmation, hold and cancellation, guarded by a state machine.

Every status change goes through `transition`, which

1. refuses any change that is not in `TRANSITIONS` (e.g. shipped -> cancelled),
2. writes one `order_status_history` row (from, to, who, why),
3. sets the milestone timestamps used by the KPIs (confirmed_at, shipped_at, ...),
4. writes an audit record.

Main flow and exceptions (project document, section 9.2):

    created -> confirmed -> inventory_reserved -> allocated -> picking -> picked
            -> packing -> packed -> shipped -> delivered -> (returned)

    confirmed -> partially_allocated / backordered  (not enough stock yet)
    shipped   -> delayed -> delivered               (late delivery)
    any open status before picking -> on_hold -> back to where it was
    any status before picking      -> cancelled     (reservations are released)

Orders cannot be cancelled once picking has started: the goods are already moving.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.catalog import Product
from app.models.inventory import ReferenceType
from app.models.order import Customer, Order, OrderItem, OrderStatus, OrderStatusHistory
from app.models.user import User
from app.schemas.order import OrderCreate
from app.services.audit_service import AuditService
from app.services.inventory_service import InventoryService

logger = get_logger(__name__)

S = OrderStatus

# Statuses an order can be cancelled or put on hold from (nothing has left a bin yet).
BEFORE_PICKING = (
    S.CREATED,
    S.CONFIRMED,
    S.INVENTORY_RESERVED,
    S.PARTIALLY_ALLOCATED,
    S.BACKORDERED,
    S.ALLOCATED,
)

# The state machine: status -> statuses it may change to.
TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    S.CREATED: frozenset({S.CONFIRMED, S.ON_HOLD, S.CANCELLED}),
    S.CONFIRMED: frozenset(
        {S.INVENTORY_RESERVED, S.PARTIALLY_ALLOCATED, S.BACKORDERED, S.ON_HOLD, S.CANCELLED}
    ),
    S.PARTIALLY_ALLOCATED: frozenset({S.INVENTORY_RESERVED, S.BACKORDERED, S.ON_HOLD, S.CANCELLED}),
    S.BACKORDERED: frozenset({S.INVENTORY_RESERVED, S.PARTIALLY_ALLOCATED, S.ON_HOLD, S.CANCELLED}),
    S.INVENTORY_RESERVED: frozenset({S.ALLOCATED, S.ON_HOLD, S.CANCELLED}),
    S.ALLOCATED: frozenset({S.PICKING, S.INVENTORY_RESERVED, S.ON_HOLD, S.CANCELLED}),
    S.PICKING: frozenset({S.PICKED}),
    S.PICKED: frozenset({S.PACKING}),
    S.PACKING: frozenset({S.PACKED}),
    S.PACKED: frozenset({S.SHIPPED}),
    S.SHIPPED: frozenset({S.DELIVERED, S.DELAYED}),
    S.DELAYED: frozenset({S.DELIVERED}),
    S.DELIVERED: frozenset({S.RETURNED}),
    # Leaving "on hold" goes back to the status the order had before (checked separately).
    S.ON_HOLD: frozenset({*BEFORE_PICKING, S.CANCELLED}),
    S.CANCELLED: frozenset(),
    S.RETURNED: frozenset(),
}

MILESTONES = {
    S.CONFIRMED: "confirmed_at",
    S.SHIPPED: "shipped_at",
    S.DELIVERED: "delivered_at",
    S.CANCELLED: "cancelled_at",
}


class OrderNotFoundError(NotFoundError):
    message = "Order not found"


class InvalidTransitionError(ConflictError):
    """The order cannot change to the requested status from its current one."""


def can_transition(current: str, target: str) -> bool:
    return OrderStatus(target) in TRANSITIONS[OrderStatus(current)]


def _label(status: str) -> str:
    return status.replace("_", " ")


class OrderService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuditService(db)

    # ------------------------------------------------------------------- read
    def get(self, order_id: int) -> Order:
        order = self.db.scalar(
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.history))
            .where(Order.id == order_id)
        )
        if order is None:
            raise OrderNotFoundError()
        return order

    # ----------------------------------------------------------------- create
    def create(self, data: OrderCreate, *, user: User | None) -> Order:
        """Place an order: prices are copied from the catalog, the address from the customer."""
        customer = self.db.get(Customer, data.customer_id)
        if customer is None:
            raise UnprocessableError("Customer not found")
        if not customer.is_active:
            raise UnprocessableError(f"Customer {customer.code} is archived")

        products = self._products([item.product_id for item in data.items])
        items = [
            OrderItem(
                line_number=number,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=products[item.product_id].unit_price,
            )
            for number, item in enumerate(data.items, start=1)
        ]
        order = Order(
            customer_id=customer.id,
            status=S.CREATED,
            priority=data.priority,
            requested_delivery_date=data.requested_delivery_date,
            notes=data.notes,
            ship_to_name=data.ship_to_name or customer.name,
            ship_to_address=data.ship_to_address or customer.address_line,
            ship_to_postal_code=data.ship_to_postal_code or customer.postal_code,
            ship_to_city=data.ship_to_city or customer.city,
            ship_to_country=data.ship_to_country or customer.country,
            subtotal=sum((i.unit_price * i.quantity for i in items), Decimal("0.00")),
            created_by_id=user.id if user else None,
        )
        order.items = items
        order.history = [
            OrderStatusHistory(to_status=S.CREATED, changed_by_id=user.id if user else None)
        ]

        order.order_number = self._next_order_number()
        self.db.add(order)
        try:
            self.db.flush()
        except IntegrityError as exc:  # another request took the same number at the same time
            self.db.rollback()
            raise ConflictError("Could not create the order, please try again") from exc
        self.audit.record(
            "order.create",
            "order",
            order.id,
            summary=(
                f"Order {order.order_number} for {customer.code}: {len(items)} line(s), "
                f"{order.subtotal} EUR"
            ),
            actor=user,
        )
        self.db.commit()
        logger.info("Created order %s", order.order_number)
        return order

    # ---------------------------------------------------------- status changes
    def confirm(self, order_id: int, *, user: User | None, note: str | None = None) -> Order:
        """Confirm the order and reserve its stock right away.

        Ends as inventory_reserved, partially_allocated or backordered.
        """
        from app.services.allocation_service import AllocationService

        order = self.get(order_id)
        self.transition(order, S.CONFIRMED, user=user, note=note)
        try:
            AllocationService(self.db).reserve_for_order(order, user=user)
        except Exception:
            self.db.rollback()
            raise
        InventoryService(self.db).commit()
        return order

    def reserve_stock(self, order_id: int, *, user: User | None) -> Order:
        """Try again to reserve the missing units of a waiting (partly) backordered order."""
        from app.services.allocation_service import WAITING, AllocationService

        order = self.get(order_id)
        if order.status not in WAITING:
            raise InvalidTransitionError(
                f"Order {order.order_number} is {_label(order.status)}; only backordered or "
                "partially allocated orders wait for stock"
            )
        try:
            AllocationService(self.db).reserve_for_order(order, user=user)
        except Exception:
            self.db.rollback()
            raise
        InventoryService(self.db).commit()
        return order

    def hold(self, order_id: int, *, user: User | None, reason: str) -> Order:
        """Stop an order before picking (e.g. payment problem); stock stays reserved."""
        order = self.get(order_id)
        previous = order.status
        self.transition(order, S.ON_HOLD, user=user, note=reason)
        order.status_before_hold = previous
        self.db.commit()
        return order

    def release_hold(self, order_id: int, *, user: User | None, note: str | None = None) -> Order:
        order = self.get(order_id)
        if order.status != S.ON_HOLD:
            raise InvalidTransitionError(f"Order {order.order_number} is not on hold")
        previous = order.status_before_hold or S.CREATED
        self.transition(order, OrderStatus(previous), user=user, note=note, releasing_hold=True)
        order.status_before_hold = None
        self.db.commit()
        return order

    def cancel(self, order_id: int, *, user: User | None, reason: str) -> Order:
        """Cancel an order that has not started picking; its reservations are released."""
        order = self.get(order_id)
        self.transition(order, S.CANCELLED, user=user, note=reason)
        order.cancel_reason = reason
        order.status_before_hold = None
        for item in order.items:
            item.quantity_reserved = 0
        from app.services.fulfillment_service import FulfillmentService  # import cycle

        FulfillmentService(self.db).cancel_open_tasks(order)
        # Commits the order change together with the released stock (one transaction).
        InventoryService(self.db).release_for_reference(
            ReferenceType.ORDER, order.id, user=user, reason=f"Order {order.order_number} cancelled"
        )
        return order

    def transition(
        self,
        order: Order,
        target: OrderStatus,
        *,
        user: User | None,
        note: str | None = None,
        releasing_hold: bool = False,
    ) -> OrderStatusHistory:
        """Change the status if the state machine allows it (no commit).

        An order on hold only moves on through `release_hold` (back to where it was) or by
        being cancelled.
        """
        current = OrderStatus(order.status)
        if target not in TRANSITIONS[current]:
            raise InvalidTransitionError(
                f"Order {order.order_number} is {_label(current)} and cannot become "
                f"{_label(target)}"
            )
        if current is S.ON_HOLD and target is not S.CANCELLED:
            if not releasing_hold:
                raise InvalidTransitionError(
                    f"Order {order.order_number} is on hold; release the hold first"
                )
            expected = order.status_before_hold or S.CREATED
            if target != expected:
                raise InvalidTransitionError(
                    f"Order {order.order_number} goes back to {_label(expected)} when released"
                )
        order.status = target
        if target in MILESTONES:
            setattr(order, MILESTONES[target], datetime.now(UTC))
        entry = OrderStatusHistory(
            from_status=current,
            to_status=target,
            note=note,
            changed_by_id=user.id if user else None,
        )
        order.history.append(entry)
        self.audit.record(
            "order.status",
            "order",
            order.id,
            summary=f"Order {order.order_number}: {_label(current)} → {_label(target)}"
            + (f" ({note})" if note else ""),
            changes={"status": {"old": current.value, "new": target.value}},
            actor=user,
        )
        return entry

    # --------------------------------------------------------------- helpers
    def _products(self, product_ids: list[int]) -> dict[int, Product]:
        found = {
            p.id: p for p in self.db.scalars(select(Product).where(Product.id.in_(product_ids)))
        }
        missing = [pid for pid in product_ids if pid not in found]
        if missing:
            raise UnprocessableError(f"Product(s) not found: {', '.join(map(str, missing))}")
        archived = [p.sku for p in found.values() if not p.is_active]
        if archived:
            raise UnprocessableError(f"Archived products cannot be ordered: {', '.join(archived)}")
        return found

    def _next_order_number(self) -> str:
        """SO-<year>-<6-digit sequence>, e.g. SO-2026-000042 (sequence restarts each year)."""
        prefix = f"SO-{datetime.now(UTC).year}-"
        last: str | None = self.db.scalar(
            select(func.max(Order.order_number)).where(Order.order_number.like(f"{prefix}%"))
        )
        sequence = int(last.removeprefix(prefix)) + 1 if last else 1
        return f"{prefix}{sequence:06d}"


def statuses_reachable_from(status: OrderStatus) -> Sequence[OrderStatus]:
    """For the UI: which status changes are possible right now."""
    return sorted(TRANSITIONS[status], key=lambda s: list(OrderStatus).index(s))
