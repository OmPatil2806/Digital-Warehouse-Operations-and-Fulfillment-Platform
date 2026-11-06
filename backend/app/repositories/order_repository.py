"""List queries for customers, orders, fulfillment work, shipments and returns. Never commits."""

from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.fulfillment import PackingTask, PickingTask
from app.models.order import Customer, Order, OrderPriority, Return
from app.models.shipment import Shipment
from app.models.warehouse import Bin

PRIORITY_RANK = case(
    {
        OrderPriority.URGENT.value: 0,
        OrderPriority.HIGH.value: 1,
        OrderPriority.NORMAL.value: 2,
        OrderPriority.LOW.value: 3,
    },
    value=Order.priority,
    else_=9,
)


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class OrderRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _page(self, query: Select, order: list[Any], offset: int, limit: int) -> tuple[list, int]:
        total = self.db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        items = list(self.db.scalars(query.order_by(*order).offset(offset).limit(limit)).unique())
        return items, total or 0

    # ----------------------------------------------------------------- customers
    def search_customers(
        self, *, offset: int, limit: int, q: str | None = None, is_active: bool | None = None
    ) -> tuple[list[Customer], int]:
        query = select(Customer)
        if q:
            pattern = _like(q)
            query = query.where(
                or_(
                    Customer.code.ilike(pattern, escape="\\"),
                    Customer.name.ilike(pattern, escape="\\"),
                    Customer.email.ilike(pattern, escape="\\"),
                )
            )
        if is_active is not None:
            query = query.where(Customer.is_active.is_(is_active))
        return self._page(query, [Customer.code], offset, limit)

    # -------------------------------------------------------------------- orders
    def search_orders(
        self,
        *,
        offset: int,
        limit: int,
        q: str | None = None,
        status: str | None = None,
        customer_id: int | None = None,
    ) -> tuple[list[Order], int]:
        """Newest first."""
        query = select(Order).options(selectinload(Order.items), selectinload(Order.customer))
        if q:
            pattern = _like(q)
            query = query.join(Customer, Order.customer_id == Customer.id).where(
                or_(
                    Order.order_number.ilike(pattern, escape="\\"),
                    Customer.name.ilike(pattern, escape="\\"),
                    Customer.code.ilike(pattern, escape="\\"),
                )
            )
        if status is not None:
            query = query.where(Order.status == status)
        if customer_id is not None:
            query = query.where(Order.customer_id == customer_id)
        return self._page(query, [Order.created_at.desc(), Order.id.desc()], offset, limit)

    # --------------------------------------------------------------- fulfillment
    def picking_queue(
        self,
        *,
        offset: int,
        limit: int,
        statuses: list[str],
        order_id: int | None = None,
        assigned_to_id: int | None = None,
    ) -> tuple[list[PickingTask], int]:
        """Urgent orders first, then the oldest; within an order along the route."""
        query = (
            select(PickingTask)
            .join(Order, PickingTask.order_id == Order.id)
            .join(Bin, PickingTask.bin_id == Bin.id)
            .where(PickingTask.status.in_(statuses))
        )
        if order_id is not None:
            query = query.where(PickingTask.order_id == order_id)
        if assigned_to_id is not None:
            query = query.where(PickingTask.assigned_to_id == assigned_to_id)
        order = [PRIORITY_RANK, Order.created_at, Order.id, PickingTask.sequence]
        return self._page(query, order, offset, limit)

    def packing_queue(
        self, *, offset: int, limit: int, statuses: list[str]
    ) -> tuple[list[PackingTask], int]:
        query = (
            select(PackingTask)
            .join(Order, PackingTask.order_id == Order.id)
            .where(PackingTask.status.in_(statuses))
        )
        return self._page(query, [PRIORITY_RANK, Order.created_at, PackingTask.id], offset, limit)

    # ------------------------------------------------------------------ shipping
    def search_shipments(
        self,
        *,
        offset: int,
        limit: int,
        status: str | None = None,
        customer_id: int | None = None,
        q: str | None = None,
    ) -> tuple[list[Shipment], int]:
        query = select(Shipment).join(Order, Shipment.order_id == Order.id)
        if status is not None:
            query = query.where(Shipment.status == status)
        if customer_id is not None:
            query = query.where(Order.customer_id == customer_id)
        if q:
            pattern = _like(q)
            query = query.where(
                or_(
                    Shipment.tracking_number.ilike(pattern, escape="\\"),
                    Order.order_number.ilike(pattern, escape="\\"),
                )
            )
        return self._page(query, [Shipment.shipped_at.desc(), Shipment.id.desc()], offset, limit)

    def search_returns(
        self,
        *,
        offset: int,
        limit: int,
        status: str | None = None,
        customer_id: int | None = None,
        order_id: int | None = None,
    ) -> tuple[list[Return], int]:
        query = select(Return).join(Order, Return.order_id == Order.id)
        if status is not None:
            query = query.where(Return.status == status)
        if customer_id is not None:
            query = query.where(Order.customer_id == customer_id)
        if order_id is not None:
            query = query.where(Return.order_id == order_id)
        return self._page(query, [Return.created_at.desc(), Return.id.desc()], offset, limit)
