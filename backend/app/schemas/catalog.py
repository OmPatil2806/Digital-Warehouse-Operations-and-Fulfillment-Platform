"""Request and response schemas for categories, suppliers and products.

Decimal values (money, weights, dimensions) are returned as JSON strings such as
"899.99" so they stay exact; requests may send them as numbers or strings.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)

# ------------------------------------------------------------------ reusable fields
Text80 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Text120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Text160 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]


def _upper(value: str) -> str:
    return value.upper()


# SKU: letters, digits, "-", "_" or "."; stored in upper case (SKUs are case-insensitive).
Sku = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=2, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    ),
    AfterValidator(_upper),
]
SupplierCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=2, max_length=20, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$"
    ),
    AfterValidator(_upper),
]
# EAN-8, UPC-A (12), EAN-13 or GTIN-14
Barcode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^(\d{8}|\d{12,14})$")]


def _fixed(places: int) -> AfterValidator:
    """Normalise to exactly `places` decimals, so 650 becomes 650.00 everywhere."""
    quantum = Decimal(1).scaleb(-places)
    return AfterValidator(lambda value: value.quantize(quantum))


Price = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2), _fixed(2)]
WeightKg = Annotated[Decimal, Field(gt=0, max_digits=9, decimal_places=3), _fixed(3)]
LengthCm = Annotated[Decimal, Field(gt=0, max_digits=7, decimal_places=1), _fixed(1)]
Reliability = Annotated[Decimal, Field(ge=0, le=1, decimal_places=2), _fixed(2)]
LeadTimeDays = Annotated[int, Field(ge=0, le=365)]
StockLevel = Annotated[int, Field(ge=0, le=10_000_000)]


class Reference(BaseModel):
    """Short summary of a related record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class SupplierReference(Reference):
    code: str


class ProductReference(Reference):
    sku: str


# ------------------------------------------------------------------------ categories
class CategoryCreate(BaseModel):
    name: Text80
    description: OptionalText | None = None
    parent_id: int | None = None


class CategoryUpdate(BaseModel):
    name: Text80 | None = None
    description: OptionalText | None = None
    parent_id: int | None = None
    is_active: bool | None = None


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    parent_id: int | None
    is_active: bool
    product_count: int = 0  # active products directly in this category
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------------- suppliers
class SupplierCreate(BaseModel):
    code: SupplierCode
    name: Text120
    contact_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None
    ) = None
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    address: OptionalText | None = None
    country: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    lead_time_days: LeadTimeDays = 7
    reliability_score: Reliability = Decimal("0.95")


class SupplierUpdate(BaseModel):
    code: SupplierCode | None = None
    name: Text120 | None = None
    contact_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None
    ) = None
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    address: OptionalText | None = None
    country: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    lead_time_days: LeadTimeDays | None = None
    reliability_score: Reliability | None = None
    is_active: bool | None = None


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    contact_name: str | None
    email: str | None
    phone: str | None
    address: str | None
    country: str | None
    lead_time_days: int
    reliability_score: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


# -------------------------------------------------------------------------- products
class ProductCreate(BaseModel):
    sku: Sku
    name: Text160
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None
    ) = None
    category_id: int
    brand: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    unit_price: Price
    unit_cost: Price
    weight_kg: WeightKg
    length_cm: LengthCm
    width_cm: LengthCm
    height_cm: LengthCm
    barcode: Barcode | None = None
    min_stock: StockLevel = 0
    max_stock: StockLevel | None = None
    default_supplier_id: int | None = None

    @model_validator(mode="after")
    def _check_stock_levels(self) -> "ProductCreate":
        if self.max_stock is not None and self.max_stock < self.min_stock:
            raise ValueError("max_stock must be greater than or equal to min_stock")
        return self


class ProductUpdate(BaseModel):
    """Partial update. min/max stock are checked again against the stored values."""

    sku: Sku | None = None
    name: Text160 | None = None
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None
    ) = None
    category_id: int | None = None
    brand: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    unit_price: Price | None = None
    unit_cost: Price | None = None
    weight_kg: WeightKg | None = None
    length_cm: LengthCm | None = None
    width_cm: LengthCm | None = None
    height_cm: LengthCm | None = None
    barcode: Barcode | None = None
    min_stock: StockLevel | None = None
    max_stock: StockLevel | None = None
    default_supplier_id: int | None = None
    is_active: bool | None = None


class ProductPublicResponse(BaseModel):
    """What every logged-in user (including customers) may see: no costs or margins."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    description: str | None
    category: Reference
    brand: str | None
    unit_price: Decimal
    weight_kg: Decimal
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal
    barcode: str | None
    is_active: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def volume_cm3(self) -> Decimal:
        return self.length_cm * self.width_cm * self.height_cm


class ProductResponse(ProductPublicResponse):
    """Full product data for warehouse users (admin, manager, staff)."""

    unit_cost: Decimal
    min_stock: int
    max_stock: int | None
    default_supplier: SupplierReference | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def margin(self) -> Decimal:
        return self.unit_price - self.unit_cost


ProductSort = Literal[
    "sku", "-sku", "name", "-name", "unit_price", "-unit_price", "created_at", "-created_at"
]
SupplierSort = Literal[
    "code",
    "-code",
    "name",
    "-name",
    "lead_time_days",
    "-lead_time_days",
    "reliability_score",
    "-reliability_score",
]


# ---------------------------------------------------------------- supplier products
class SupplierProductCreate(BaseModel):
    product_id: int
    supplier_sku: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = (
        None
    )
    unit_cost: Price
    lead_time_days: LeadTimeDays | None = None
    min_order_qty: Annotated[int, Field(ge=1, le=1_000_000)] = 1
    is_preferred: bool = False


class SupplierProductUpdate(BaseModel):
    supplier_sku: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = (
        None
    )
    unit_cost: Price | None = None
    lead_time_days: LeadTimeDays | None = None
    min_order_qty: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    is_preferred: bool | None = None


class SupplierProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier: SupplierReference
    product: ProductReference
    supplier_sku: str | None
    unit_cost: Decimal
    lead_time_days: int | None
    effective_lead_time_days: int
    min_order_qty: int
    is_preferred: bool
