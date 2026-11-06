"""Request and response schemas for customers, orders and returns."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.order import CustomerType, OrderPriority
from app.schemas.common import Page
from app.schemas.inventory import BinRef, ProductRef, UserRef

MAX_LINES = 100
MAX_LINE_QUANTITY = 100_000

OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: Annotated[int, Field(ge=1, le=MAX_LINE_QUANTITY)]


class OrderCreate(BaseModel):
    """A new order. The shipping address defaults to the customer's address."""

    customer_id: int
    items: Annotated[list[OrderItemCreate], Field(min_length=1, max_length=MAX_LINES)]
    priority: OrderPriority = OrderPriority.NORMAL
    requested_delivery_date: date | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    ship_to_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
        | None
    ) = None
    ship_to_address: OptionalText | None = None
    ship_to_postal_code: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None
    ) = None
    ship_to_city: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None
    ) = None
    ship_to_country: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None
    ) = None

    @model_validator(mode="after")
    def _one_line_per_product(self) -> "OrderCreate":
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("each product may appear only once; add up the quantities instead")
        return self

    @field_validator("requested_delivery_date")
    @classmethod
    def _not_in_the_past(cls, value: date | None) -> date | None:
        if value is not None and value < datetime.now(UTC).date():
            raise ValueError("the requested delivery date cannot be in the past")
        return value


class StatusNote(BaseModel):
    """Optional note for a status change (e.g. confirming an order)."""

    note: OptionalText | None = None


class ReasonRequest(BaseModel):
    """Holding or cancelling an order always needs a reason."""

    reason: Reason


# =========================================================================== customers
class CustomerCreate(BaseModel):
    """A new customer. The code is generated (CUST-0001, ...) when left empty."""

    code: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True, min_length=2, max_length=20, pattern=r"^[A-Za-z0-9-]+$"
            ),
        ]
        | None
    ) = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    customer_type: CustomerType = CustomerType.BUSINESS
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    address_line: OptionalText | None = None
    postal_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = (
        None
    )
    city: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    country: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    user_id: int | None = None  # a login with the customer role


class CustomerUpdate(BaseModel):
    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
        | None
    ) = None
    customer_type: CustomerType | None = None
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    address_line: OptionalText | None = None
    postal_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = (
        None
    )
    city: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    country: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    user_id: int | None = None
    is_active: bool | None = None


class CustomerRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class CustomerResponse(CustomerRef):
    customer_type: str
    email: str | None
    phone: str | None
    address_line: str | None
    postal_code: str | None
    city: str | None
    country: str | None
    user_id: int | None
    is_active: bool
    created_at: datetime


# ============================================================================== orders
class WarehouseRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_number: int
    product: ProductRef
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    quantity_reserved: int
    quantity_picked: int
    quantity_packed: int
    quantity_shipped: int
    quantity_returned: int


class OrderHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: str | None
    to_status: str
    note: str | None
    changed_by: UserRef | None
    created_at: datetime


class OrderSummary(BaseModel):
    """An order in a list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: str
    customer: CustomerRef
    status: str
    priority: str
    subtotal: Decimal
    total_quantity: int
    requested_delivery_date: date | None
    created_at: datetime


class OrderResponse(OrderSummary):
    warehouse: WarehouseRef | None
    ship_to_name: str
    ship_to_address: str | None
    ship_to_postal_code: str | None
    ship_to_city: str | None
    ship_to_country: str | None
    notes: str | None
    confirmed_at: datetime | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    items: list[OrderItemResponse]
    history: list[OrderHistoryResponse]
    # Status changes that are possible now (for the buttons in the UI).
    next_statuses: list[str] = []


# ============================================================================= returns
class ReturnItemResponse(BaseModel):
    id: int
    product: ProductRef
    quantity: int
    condition: str | None
    bin: BinRef | None
    note: str | None


class ReturnResponse(BaseModel):
    id: int
    return_number: str
    order_id: int
    order_number: str
    status: str
    reason: str
    created_at: datetime
    completed_at: datetime | None
    items: list[ReturnItemResponse]


CustomerPage = Page[CustomerResponse]
OrderPage = Page[OrderSummary]
ReturnPage = Page[ReturnResponse]
