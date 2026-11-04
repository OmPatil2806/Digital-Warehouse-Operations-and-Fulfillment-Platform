"""Catalog tables: categories, products, suppliers and which supplier sells what.

Units: weights in kg, dimensions in cm, volumes in cm³, money in the shop currency.
Money and measurements use `ScaledDecimal` so values stay exact (see app.database.types).

Nothing here is ever hard-deleted once it is in use: rows are archived with
`is_active = False` so that orders and stock movements (later phases) keep their history.
"""

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import ScaledDecimal
from app.models.mixins import IdMixin, TimestampMixin

Money = ScaledDecimal(scale=2)  # e.g. 19.99
Weight = ScaledDecimal(scale=3)  # kg with gram precision, e.g. 1.250
Length = ScaledDecimal(scale=1)  # cm with millimetre precision, e.g. 35.5


class Category(IdMixin, TimestampMixin, Base):
    """A product category. Categories can be nested (e.g. Electronics > Laptops)."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
    )

    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    parent: Mapped["Category | None"] = relationship(
        remote_side="Category.id", back_populates="children"
    )
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    products: Mapped[list["Product"]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        return f"<Category {self.name}>"


class Supplier(IdMixin, TimestampMixin, Base):
    """A company that supplies products to the warehouse."""

    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint("lead_time_days >= 0", name="lead_time_not_negative"),
        CheckConstraint("reliability_score BETWEEN 0 AND 100", name="reliability_range"),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # e.g. SUP-001
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(80))
    # Typical days between ordering and receiving goods.
    lead_time_days: Mapped[int] = mapped_column(default=7, server_default="7", nullable=False)
    # Share of deliveries that arrive on time and complete: 0.00 – 1.00.
    reliability_score: Mapped[Decimal] = mapped_column(
        ScaledDecimal(scale=2), default=Decimal("0.95"), server_default="95", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    supplied_products: Mapped[list["SupplierProduct"]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Supplier {self.code}>"


class Product(IdMixin, TimestampMixin, Base):
    """A stock-keeping unit (SKU) that can be stored, ordered and shipped."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="price_not_negative"),
        CheckConstraint("unit_cost >= 0", name="cost_not_negative"),
        CheckConstraint("weight_kg > 0", name="weight_positive"),
        CheckConstraint(
            "length_cm > 0 AND width_cm > 0 AND height_cm > 0", name="dimensions_positive"
        ),
        CheckConstraint("min_stock >= 0", name="min_stock_not_negative"),
        CheckConstraint("max_stock IS NULL OR max_stock >= min_stock", name="max_stock_gte_min"),
    )

    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    brand: Mapped[str | None] = mapped_column(String(80))
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)  # selling price
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False)  # purchase cost
    weight_kg: Mapped[Decimal] = mapped_column(Weight, nullable=False)
    length_cm: Mapped[Decimal] = mapped_column(Length, nullable=False)
    width_cm: Mapped[Decimal] = mapped_column(Length, nullable=False)
    height_cm: Mapped[Decimal] = mapped_column(Length, nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(64), unique=True)  # EAN/UPC, optional
    min_stock: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    max_stock: Mapped[int | None] = mapped_column()
    default_supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), index=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    category: Mapped[Category] = relationship(back_populates="products")
    default_supplier: Mapped[Supplier | None] = relationship()
    supplier_links: Mapped[list["SupplierProduct"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def volume_cm3(self) -> Decimal:
        """Outer volume of one unit."""
        return self.length_cm * self.width_cm * self.height_cm

    @property
    def margin(self) -> Decimal:
        """Profit per unit (price minus cost)."""
        return self.unit_price - self.unit_cost

    def __repr__(self) -> str:
        return f"<Product {self.sku}>"


class SupplierProduct(IdMixin, TimestampMixin, Base):
    """A product as offered by one supplier (their SKU, price, lead time, order size)."""

    __tablename__ = "supplier_products"
    __table_args__ = (
        UniqueConstraint("supplier_id", "product_id"),
        CheckConstraint("unit_cost >= 0", name="cost_not_negative"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="lead_time_ok"),
        CheckConstraint("min_order_qty >= 1", name="min_order_qty_positive"),
    )

    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    supplier_sku: Mapped[str | None] = mapped_column(String(60))
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False)
    # Overrides the supplier's default lead time for this product when set.
    lead_time_days: Mapped[int | None] = mapped_column()
    min_order_qty: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    is_preferred: Mapped[bool] = mapped_column(default=False, server_default="0", nullable=False)

    supplier: Mapped[Supplier] = relationship(back_populates="supplied_products")
    product: Mapped[Product] = relationship(back_populates="supplier_links")

    @property
    def effective_lead_time_days(self) -> int:
        return (
            self.lead_time_days if self.lead_time_days is not None else self.supplier.lead_time_days
        )

    def __repr__(self) -> str:
        return f"<SupplierProduct supplier={self.supplier_id} product={self.product_id}>"
