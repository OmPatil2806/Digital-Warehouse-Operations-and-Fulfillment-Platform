"""Supplier purchase orders: how new stock is ordered and received.

draft -> ordered -> partially_received -> received
  \\________\\_________________________/-> cancelled (only while nothing was received)

A purchase order (PO) buys products from one supplier for one warehouse. Each line has
an ordered quantity, the agreed unit cost (from the supplier's offer) and how much has
arrived so far. Goods are received line by line into bins: every receipt writes a
normal RECEIPT inventory movement whose reason names the PO, and an audit record.
A PO not fully received by its expected date raises an "overdue supplier" alert.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime
from app.models.catalog import Money, Product, Supplier
from app.models.mixins import IdMixin, TimestampMixin, one_of
from app.models.user import User
from app.models.warehouse import Warehouse


class PurchaseOrderStatus(StrEnum):
    DRAFT = "draft"  # being prepared, can still be changed or cancelled
    ORDERED = "ordered"  # sent to the supplier, waiting for the goods
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"  # every line arrived in full
    CANCELLED = "cancelled"


OPEN_PO_STATUSES = (
    PurchaseOrderStatus.ORDERED.value,
    PurchaseOrderStatus.PARTIALLY_RECEIVED.value,
)


class PurchaseOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (CheckConstraint(one_of("status", PurchaseOrderStatus), name="valid_status"),)

    po_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=PurchaseOrderStatus.DRAFT,
        server_default="draft",
        index=True,
    )
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    ordered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    supplier: Mapped[Supplier] = relationship()
    warehouse: Mapped[Warehouse] = relationship()
    created_by: Mapped[User | None] = relationship()
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PurchaseOrderItem.id",
    )

    @property
    def is_overdue(self) -> bool:
        """Still waiting for goods after the expected date."""
        return self.status in OPEN_PO_STATUSES and self.expected_date < datetime.now(UTC).date()

    @property
    def total_cost(self) -> Decimal:
        return sum((i.unit_cost * i.quantity for i in self.items), Decimal("0"))

    def __repr__(self) -> str:
        return f"<PurchaseOrder {self.po_number} {self.status}>"


class PurchaseOrderItem(IdMixin, Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        UniqueConstraint(
            "purchase_order_id",
            "product_id",
            name="uq_purchase_order_items_purchase_order_id_product_id",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="cost_not_negative"),
        CheckConstraint(
            "quantity_received >= 0 AND quantity_received <= quantity",
            name="received_range",
        ),
    )

    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False)
    quantity_received: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    @property
    def quantity_outstanding(self) -> int:
        return self.quantity - self.quantity_received

    def __repr__(self) -> str:
        return f"<PurchaseOrderItem {self.product_id} {self.quantity_received}/{self.quantity}>"
