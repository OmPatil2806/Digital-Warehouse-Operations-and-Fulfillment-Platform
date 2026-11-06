"""Request schemas for picking, packing and shipping."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class PickConfirmation(BaseModel):
    """What the picker scanned and how many units they took."""

    bin_code: Code  # the bin's location code, e.g. WH01-ZA-R01-S01-B01
    product_code: Code  # the product's SKU or barcode
    quantity_picked: Annotated[int, Field(ge=0, le=100_000)]
    # Required when fewer units were picked than the task asks for.
    short_reason: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
        | None
    ) = None


class PackedLine(BaseModel):
    product_id: int
    quantity: Annotated[int, Field(ge=0, le=100_000)]


class PackConfirmation(BaseModel):
    """What the packer counted into the parcels, and the parcels themselves."""

    items: Annotated[list[PackedLine], Field(min_length=1, max_length=100)]
    package_count: Annotated[int, Field(ge=1, le=100)]
    weight_kg: Annotated[Decimal, Field(gt=0, max_digits=9, decimal_places=3)]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None


class ShipmentCreate(BaseModel):
    """Hand a packed order to a carrier."""

    carrier_id: int
    # Leave empty to generate one (e.g. labels printed by the warehouse system).
    tracking_number: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True, min_length=4, max_length=40, pattern=r"^[A-Za-z0-9-]+$"
            ),
        ]
        | None
    ) = None
    # Defaults to today + the carrier's transit days (working days).
    expected_delivery_date: date | None = None


Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]


class ShipmentEventCreate(BaseModel):
    """A tracking update from the carrier (or entered by staff)."""

    event_type: Literal["in_transit", "out_for_delivery", "delayed", "delivered", "exception"]
    occurred_at: datetime | None = None  # default: now
    location: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    description: Text | None = None

    @model_validator(mode="after")
    def _exception_needs_text(self) -> "ShipmentEventCreate":
        if self.event_type == "exception" and not self.description:
            raise ValueError("describe the exception (e.g. address not found)")
        return self


class ReturnLine(BaseModel):
    product_id: int
    quantity: Annotated[int, Field(ge=1, le=100_000)]


class ReturnCreate(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]
    items: Annotated[list[ReturnLine], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def _one_line_per_product(self) -> "ReturnCreate":
        ids = [line.product_id for line in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("each product may appear only once")
        return self


class InspectedLine(BaseModel):
    product_id: int
    condition: Literal["restock", "damaged"]
    # Where the units go; default: a bin of the returns zone that has room.
    bin_id: int | None = None
    note: Text | None = None


class ReturnInspection(BaseModel):
    items: Annotated[list[InspectedLine], Field(min_length=1, max_length=100)]
