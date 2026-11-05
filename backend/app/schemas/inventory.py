"""Request schemas for inventory operations (responses are added with the endpoints)."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.models.inventory import AdjustmentKind, ReferenceType

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


class ReserveRequest(BaseModel):
    """Hold available units of a product, e.g. for an order.

    With `bin_id`, units are held in that bin. Without it, the system picks the bins:
    picking zones first, then the racks closest to packing (shortest walk for pickers).
    """

    product_id: int
    quantity: Quantity
    bin_id: int | None = None
    reference_type: ReferenceType | None = None  # what the units are held for
    reference_id: int | None = None
    reason: OptionalReason | None = None

    @model_validator(mode="after")
    def _reference_complete(self) -> "ReserveRequest":
        if (self.reference_type is None) != (self.reference_id is None):
            raise ValueError("reference_type and reference_id must be given together")
        return self


class ReleaseRequest(BaseModel):
    reason: OptionalReason | None = None


class TransferRequest(BaseModel):
    """Move available units of a product from one bin to another."""

    product_id: int
    from_bin_id: int
    to_bin_id: int
    quantity: Quantity
    reason: OptionalReason | None = None

    @model_validator(mode="after")
    def _different_bins(self) -> "TransferRequest":
        if self.from_bin_id == self.to_bin_id:
            raise ValueError("from_bin_id and to_bin_id must be different bins")
        return self
