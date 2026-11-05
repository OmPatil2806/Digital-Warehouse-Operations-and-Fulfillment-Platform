"""Request schemas for inventory operations (responses are added with the endpoints)."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.inventory import AdjustmentKind

# One operation moves at most a million units (protects against typos like 1000000000).
MAX_QUANTITY = 1_000_000
Quantity = Annotated[int, Field(ge=1, le=MAX_QUANTITY)]
OptionalReason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


class ReceiveRequest(BaseModel):
    """Goods arrived and were put away into a bin."""

    product_id: int
    bin_id: int
    quantity: Quantity
    # e.g. supplier delivery note or purchase order number
    reason: OptionalReason | None = None


class AdjustmentRequest(BaseModel):
    """A correction: units found / lost, damaged, restored or written off."""

    product_id: int
    bin_id: int
    kind: AdjustmentKind
    quantity: Quantity
    reason: Reason  # always required: every correction must be explainable
