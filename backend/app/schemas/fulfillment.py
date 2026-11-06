"""Request schemas for picking, packing and shipping."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

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
