"""Customers, sales orders, their lines and the status history of every order.

Order lifecycle (project document, section 9.2):

    created -> confirmed -> inventory_reserved -> allocated -> picking -> picked
            -> packing -> packed -> shipped -> delivered

    exception states: partially_allocated, backordered, on_hold, cancelled, returned, delayed

The allowed transitions are defined in the order service (state machine); every change
writes one `order_status_history` row. Each order line keeps how many units were
reserved, picked, packed, shipped and returned; database CHECK constraints guarantee the
numbers can only flow forward (returned <= shipped <= packed <= picked <= ordered).
Prices are copied from the catalog when the order is placed, so later price changes do
not alter existing orders.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime
from app.models.catalog import Money, Product
from app.models.mixins import IdMixin, TimestampMixin, one_of
from app.models.user import User
from app.models.warehouse import Warehouse


class CustomerType(StrEnum):
    BUSINESS = "business"
    CONSUMER = "consumer"


class OrderStatus(StrEnum):
    # main flow
    CREATED = "created"
    CONFIRMED = "confirmed"
    INVENTORY_RESERVED = "inventory_reserved"
    ALLOCATED = "allocated"  # picking tasks generated
    PICKING = "picking"
    PICKED = "picked"
    PACKING = "packing"
    PACKED = "packed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    # exceptions
    PARTIALLY_ALLOCATED = "partially_allocated"  # some lines could be reserved
    BACKORDERED = "backordered"  # nothing could be reserved yet
    ON_HOLD = "on_hold"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    DELAYED = "delayed"  # shipped, but the expected delivery date has passed


class OrderPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Customer(IdMixin, TimestampMixin, Base):
    """Someone who orders. May be linked to a login with the customer role (self-service);
    business customers without a login are ordered for by managers."""

    __tablename__ = "customers"
    __table_args__ = (CheckConstraint(one_of("customer_type", CustomerType), name="valid_type"),)

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # CUST-0001
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_type: Mapped[str] = mapped_column(
        String(20), default=CustomerType.BUSINESS, server_default="business"
    )
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    address_line: Mapped[str | None] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(80))
    # The login that may place orders for this customer (one customer per login).
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    user: Mapped[User | None] = relationship()
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")

    def __repr__(self) -> str:
        return f"<Customer {self.code}>"


class Order(IdMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(one_of("status", OrderStatus), name="valid_status"),
        CheckConstraint(one_of("priority", OrderPriority), name="valid_priority"),
        CheckConstraint("subtotal >= 0", name="subtotal_not_negative"),
        Index("ix_orders_customer_id_created_at", "customer_id", "created_at"),
    )

    order_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    # Warehouse that fulfills the order (NULL = not decided yet).
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), default=OrderStatus.CREATED, server_default="created", index=True
    )
    priority: Mapped[str] = mapped_column(
        String(10), default=OrderPriority.NORMAL, server_default="normal"
    )
    requested_delivery_date: Mapped[date | None] = mapped_column(Date)
    # Shipping address, copied from the customer when the order is placed.
    ship_to_name: Mapped[str] = mapped_column(String(160), nullable=False)
    ship_to_address: Mapped[str | None] = mapped_column(String(255))
    ship_to_postal_code: Mapped[str | None] = mapped_column(String(20))
    ship_to_city: Mapped[str | None] = mapped_column(String(100))
    ship_to_country: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    subtotal: Mapped[Decimal] = mapped_column(
        Money, default=Decimal("0.00"), server_default="0", nullable=False
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # Milestones (for KPIs such as order cycle time in Phase 6)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    shipped_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    # The status to go back to when an order leaves "on_hold".
    status_before_hold: Mapped[str | None] = mapped_column(String(30))

    customer: Mapped[Customer] = relationship(back_populates="orders")
    warehouse: Mapped[Warehouse | None] = relationship()
    created_by: Mapped[User | None] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="OrderItem.line_number",
    )
    history: Mapped[list["OrderStatusHistory"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="OrderStatusHistory.id",
    )

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    def __repr__(self) -> str:
        return f"<Order {self.order_number} {self.status}>"


class OrderItem(IdMixin, Base):
    """One line of an order and how far it has come through fulfillment."""

    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "line_number", name="uq_order_items_order_id_line_number"),
        UniqueConstraint("order_id", "product_id", name="uq_order_items_order_id_product_id"),
        CheckConstraint("line_number >= 1", name="line_number_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="price_not_negative"),
        CheckConstraint(
            "quantity_reserved >= 0 AND quantity_reserved <= quantity", name="reserved_in_range"
        ),
        CheckConstraint(
            "quantity_picked >= 0 AND quantity_picked <= quantity", name="picked_in_range"
        ),
        CheckConstraint(
            "quantity_packed >= 0 AND quantity_packed <= quantity_picked", name="packed_le_picked"
        ),
        CheckConstraint(
            "quantity_shipped >= 0 AND quantity_shipped <= quantity_packed",
            name="shipped_le_packed",
        ),
        CheckConstraint(
            "quantity_returned >= 0 AND quantity_returned <= quantity_shipped",
            name="returned_le_shipped",
        ),
    )

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)  # copied from the catalog
    quantity_reserved: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    quantity_picked: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    quantity_packed: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    quantity_shipped: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    quantity_returned: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    @property
    def quantity_missing(self) -> int:
        """Units still to be reserved (backordered)."""
        return self.quantity - self.quantity_reserved - self.quantity_picked

    def __repr__(self) -> str:
        return f"<OrderItem {self.line_number}: {self.quantity} x product {self.product_id}>"


class OrderStatusHistory(IdMixin, Base):
    """One status change of an order: from, to, who, when and why."""

    __tablename__ = "order_status_history"
    __table_args__ = (
        CheckConstraint(
            f"from_status IS NULL OR {one_of('from_status', OrderStatus)}", name="valid_from"
        ),
        CheckConstraint(one_of("to_status", OrderStatus), name="valid_to"),
        CheckConstraint("from_status IS NULL OR from_status != to_status", name="is_a_change"),
    )

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(30))  # NULL for the first entry
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    changed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    order: Mapped[Order] = relationship(back_populates="history")
    changed_by: Mapped[User | None] = relationship()

    def __repr__(self) -> str:
        return f"<OrderStatusHistory {self.from_status} -> {self.to_status}>"


class ReturnStatus(StrEnum):
    OPEN = "open"  # announced by the customer, goods on the way back
    COMPLETED = "completed"  # received and inspected; stock updated
    CANCELLED = "cancelled"  # the customer kept the goods after all


class ReturnCondition(StrEnum):
    RESTOCK = "restock"  # as new: back into sellable stock
    DAMAGED = "damaged"  # into stock as damaged units (to be written off or repaired)


class Return(IdMixin, TimestampMixin, Base):
    """A customer return of (some of) the shipped units of an order."""

    __tablename__ = "returns"
    __table_args__ = (CheckConstraint(one_of("status", ReturnStatus), name="valid_status"),)

    return_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=ReturnStatus.OPEN, server_default="open", index=True
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    inspected_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    order: Mapped[Order] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    inspected_by: Mapped[User | None] = relationship(foreign_keys=[inspected_by_id])
    items: Mapped[list["ReturnItem"]] = relationship(
        back_populates="return_",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ReturnItem.id",
    )

    def __repr__(self) -> str:
        return f"<Return {self.return_number} {self.status}>"


class ReturnItem(IdMixin, Base):
    __tablename__ = "return_items"
    __table_args__ = (
        UniqueConstraint(
            "return_id", "order_item_id", name="uq_return_items_return_id_order_item_id"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            f"condition IS NULL OR {one_of('condition', ReturnCondition)}", name="valid_condition"
        ),
    )

    return_id: Mapped[int] = mapped_column(
        ForeignKey("returns.id", ondelete="CASCADE"), nullable=False
    )
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    condition: Mapped[str | None] = mapped_column(String(20))  # set at inspection
    # Where the units were put back (a bin in the returns zone by default).
    bin_id: Mapped[int | None] = mapped_column(ForeignKey("bins.id", ondelete="RESTRICT"))
    note: Mapped[str | None] = mapped_column(String(255))

    return_: Mapped[Return] = relationship(back_populates="items")
    order_item: Mapped[OrderItem] = relationship()

    def __repr__(self) -> str:
        return f"<ReturnItem {self.quantity} x item {self.order_item_id} {self.condition}>"
