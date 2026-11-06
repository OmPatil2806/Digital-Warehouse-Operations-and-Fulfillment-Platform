"""Picking (and, from the next step, packing) work for orders.

One picking task per stock reservation of an order: "take N units of product P from bin
B". Tasks of an order are numbered in walking order (`sequence`), so a picker follows
one efficient route through the warehouse and ends near the packing station.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime
from app.models.catalog import Product
from app.models.inventory import StockReservation
from app.models.mixins import IdMixin, TimestampMixin, one_of
from app.models.order import Order, OrderItem
from app.models.user import User
from app.models.warehouse import Bin


class PickingTaskStatus(StrEnum):
    PENDING = "pending"  # waiting for a picker
    IN_PROGRESS = "in_progress"  # a picker is on the way
    COMPLETED = "completed"  # all units picked
    SHORT = "short"  # fewer units found than expected (short pick)
    CANCELLED = "cancelled"  # the order was cancelled before picking


OPEN_PICKING_STATUSES = (PickingTaskStatus.PENDING.value, PickingTaskStatus.IN_PROGRESS.value)


class PickingTask(IdMixin, TimestampMixin, Base):
    __tablename__ = "picking_tasks"
    __table_args__ = (
        CheckConstraint(one_of("status", PickingTaskStatus), name="valid_status"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(
            "quantity_picked IS NULL OR (quantity_picked >= 0 AND quantity_picked <= quantity)",
            name="picked_in_range",
        ),
        CheckConstraint(
            "status NOT IN ('completed', 'short') OR quantity_picked IS NOT NULL",
            name="done_has_quantity",
        ),
        Index("ix_picking_tasks_order_id_sequence", "order_id", "sequence"),
    )

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("stock_reservations.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    bin_id: Mapped[int] = mapped_column(
        ForeignKey("bins.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)  # to pick
    quantity_picked: Mapped[int | None] = mapped_column()  # set when done
    sequence: Mapped[int] = mapped_column(nullable=False)  # position on the picking route
    status: Mapped[str] = mapped_column(
        String(20), default=PickingTaskStatus.PENDING, server_default="pending", index=True
    )
    assigned_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    short_reason: Mapped[str | None] = mapped_column(String(255))

    order: Mapped[Order] = relationship()
    order_item: Mapped[OrderItem] = relationship()
    reservation: Mapped[StockReservation] = relationship()
    product: Mapped[Product] = relationship()
    bin: Mapped[Bin] = relationship()
    assigned_to: Mapped[User | None] = relationship()

    def __repr__(self) -> str:
        return f"<PickingTask {self.id} #{self.sequence} x{self.quantity} {self.status}>"
