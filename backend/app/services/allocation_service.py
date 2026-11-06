"""Reserving stock for orders, and filling backorders when stock arrives.

When an order is confirmed, every line gets as many units reserved as are available,
from ONE warehouse (the one that can cover the most units). Bins are chosen like any
reservation: picking zones first, then racks closest to packing.

    all lines fully reserved   -> inventory_reserved
    some units reserved        -> partially_allocated
    nothing reserved           -> backordered

Each reservation references the order ("order", order id), so cancelling the order
releases exactly its units. Whenever stock changes (goods received, a reservation
released, a cycle count found units, ...), `retry_backorders` tries again for the waiting
orders of the products involved: urgent orders first, then the oldest.
"""

from collections.abc import Iterable

from sqlalchemy import case, select
from sqlalchemy.orm import Session, selectinload

from app.core.logging import get_logger
from app.models.inventory import ReferenceType
from app.models.order import Order, OrderItem, OrderPriority, OrderStatus
from app.models.user import User
from app.repositories.inventory_repository import InventoryRepository
from app.services.inventory_service import InventoryService

logger = get_logger(__name__)

S = OrderStatus
WAITING = (S.PARTIALLY_ALLOCATED.value, S.BACKORDERED.value)
RESERVABLE = (S.CONFIRMED.value, *WAITING)
PRIORITY_RANK = {
    OrderPriority.URGENT.value: 0,
    OrderPriority.HIGH.value: 1,
    OrderPriority.NORMAL.value: 2,
    OrderPriority.LOW.value: 3,
}
# Re-entrancy guard: reserving for backorders is itself a stock change.
RUNNING_KEY = "_allocating_backorders"


class AllocationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.inventory = InventoryService(db)
        self.repo = InventoryRepository(db)

    def reserve_for_order(self, order: Order, *, user: User | None) -> OrderStatus:
        """Reserve what is available for every open line and set the status (no commit).

        Only for confirmed, partially allocated or backordered orders.
        """
        from app.services.order_service import OrderService  # avoids an import cycle

        if order.status not in RESERVABLE:
            return OrderStatus(order.status)
        open_items = [item for item in order.items if item.quantity_missing > 0]
        if open_items and order.warehouse_id is None:
            order.warehouse_id = self._best_warehouse(open_items)

        reference = (ReferenceType.ORDER, order.id)
        for item in open_items:
            if order.warehouse_id is None:
                break  # no stock anywhere
            result = self.inventory.reserve_available(
                item.product,
                item.quantity_missing,
                reference=reference,
                warehouse_id=order.warehouse_id,
                user=user,
                reason=f"Order {order.order_number}",
            )
            item.quantity_reserved += result.quantity

        target = self._status_for(order)
        if target != order.status:
            reserved = sum(i.quantity_reserved for i in order.items)
            OrderService(self.db).transition(
                order,
                target,
                user=user,
                note=f"{reserved} of {order.total_quantity} units reserved",
            )
        return target

    def retry_backorders(self, product_ids: Iterable[int]) -> list[Order]:
        """Try again for waiting orders that contain these products (no commit)."""
        product_ids = sorted(set(product_ids))
        if not product_ids or self.db.info.get(RUNNING_KEY):
            return []
        self.db.info[RUNNING_KEY] = True
        try:
            orders = self.db.scalars(
                select(Order)
                .options(selectinload(Order.items).selectinload(OrderItem.product))
                .where(
                    Order.status.in_(WAITING),
                    Order.id.in_(
                        select(OrderItem.order_id).where(OrderItem.product_id.in_(product_ids))
                    ),
                )
                .order_by(
                    case(PRIORITY_RANK, value=Order.priority, else_=9),
                    Order.created_at,
                    Order.id,
                )
            ).all()
            changed = []
            for order in orders:
                before = order.status
                if self.reserve_for_order(order, user=None) != before:
                    changed.append(order)
            if changed:
                logger.info("Backorders updated: %s", ", ".join(o.order_number for o in changed))
            return changed
        finally:
            self.db.info.pop(RUNNING_KEY, None)

    # --------------------------------------------------------------- helpers
    def _best_warehouse(self, items: list[OrderItem]) -> int | None:
        """The warehouse that can cover the most of the missing units (ties: lowest id)."""
        available = self.repo.available_by_warehouse([i.product_id for i in items])
        coverage: dict[int, int] = {}
        for (product_id, warehouse_id), units in available.items():
            missing = next(i.quantity_missing for i in items if i.product_id == product_id)
            coverage[warehouse_id] = coverage.get(warehouse_id, 0) + min(units, missing)
        best = [(-units, wh) for wh, units in coverage.items() if units > 0]
        return min(best)[1] if best else None

    @staticmethod
    def _status_for(order: Order) -> OrderStatus:
        if all(item.quantity_missing == 0 for item in order.items):
            return S.INVENTORY_RESERVED
        if any(item.quantity_reserved > 0 for item in order.items):
            return S.PARTIALLY_ALLOCATED
        return S.BACKORDERED
