"""Request schemas for picking (and packing, next step)."""

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
