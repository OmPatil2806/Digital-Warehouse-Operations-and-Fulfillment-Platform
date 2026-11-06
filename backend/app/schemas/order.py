"""Request schemas for orders (responses are added with the endpoints)."""

from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.models.order import OrderPriority

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
