"""Request and response schemas for inventory, approvals, cycle counts and alerts."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.inventory import AdjustmentKind, ReferenceType
from app.schemas.common import Page

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


class DecisionRequest(BaseModel):
    """A manager's note when approving (optional) or rejecting (required) a request."""

    note: OptionalReason | None = None


class RejectRequest(BaseModel):
    note: Reason  # the requester must learn why


class CycleCountStart(BaseModel):
    bin_id: int
    note: OptionalReason | None = None


class CycleCountEntry(BaseModel):
    product_id: int
    counted_quantity: Annotated[int, Field(ge=0, le=MAX_QUANTITY)]


class CycleCountRecord(BaseModel):
    """Counted quantities; may be sent several times while the count is open."""

    lines: Annotated[list[CycleCountEntry], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def _one_entry_per_product(self) -> "CycleCountRecord":
        ids = [line.product_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("each product may appear only once")
        return self


# =============================================================================== responses
class ProductRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str


class BinRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    location_code: str


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str


class InventoryResponse(BaseModel):
    """Stock of one product in one bin."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    product: ProductRef
    bin: BinRef
    quantity_on_hand: int
    quantity_reserved: int
    quantity_damaged: int
    quantity_available: int
    updated_at: datetime


class ProductStockResponse(BaseModel):
    """Where a product is stored and how much of it, over all bins."""

    product: ProductRef
    min_stock: int
    quantity_on_hand: int
    quantity_reserved: int
    quantity_damaged: int
    quantity_available: int
    is_low_stock: bool
    bins: list[InventoryResponse]


class MovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    movement_type: str
    product: ProductRef
    bin: BinRef
    quantity: int
    on_hand_delta: int
    reserved_delta: int
    damaged_delta: int
    on_hand_after: int
    reserved_after: int
    damaged_after: int
    reference_type: str | None
    reference_id: int | None
    reason: str | None
    created_by: UserRef | None


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    status: str
    product: ProductRef
    bin: BinRef
    quantity: int
    reference_type: str | None
    reference_id: int | None
    reason: str | None
    created_by: UserRef | None
    closed_at: datetime | None


class _DocumentFields(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    status: str
    product: ProductRef
    quantity: int
    requested_by: UserRef | None
    decided_by: UserRef | None
    decided_at: datetime | None
    decision_note: str | None


class TransferResponse(_DocumentFields):
    from_bin: BinRef
    to_bin: BinRef
    reason: str | None


class AdjustmentResponse(_DocumentFields):
    bin: BinRef
    kind: str
    reason: str


class TransferSubmitResponse(BaseModel):
    """`applied` = done now; otherwise the transfer waits for a manager (status pending)."""

    applied: bool
    transfer: TransferResponse


class AdjustmentSubmitResponse(BaseModel):
    applied: bool
    adjustment: AdjustmentResponse


class ApprovalQueueResponse(BaseModel):
    adjustments: list[AdjustmentResponse]
    transfers: list[TransferResponse]


class CycleCountLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product: ProductRef
    expected_quantity: int
    counted_quantity: int | None
    variance: int | None


class CycleCountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    status: str
    bin: BinRef
    note: str | None
    requested_by: UserRef | None
    submitted_at: datetime | None
    decided_by: UserRef | None
    decided_at: datetime | None
    decision_note: str | None
    lines: list[CycleCountLineResponse]


class CycleCountSummary(BaseModel):
    """A count in a list (without its lines)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    status: str
    bin: BinRef
    requested_by: UserRef | None
    submitted_at: datetime | None


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    alert_type: str
    severity: str
    status: str
    title: str
    message: str | None
    product: ProductRef | None
    bin: BinRef | None
    acknowledged_by: UserRef | None
    acknowledged_at: datetime | None
    resolved_by: UserRef | None
    resolved_at: datetime | None


InventoryPage = Page[InventoryResponse]
MovementPage = Page[MovementResponse]
ReservationPage = Page[ReservationResponse]
TransferPage = Page[TransferResponse]
AdjustmentPage = Page[AdjustmentResponse]
CycleCountPage = Page[CycleCountSummary]
AlertPage = Page[AlertResponse]
