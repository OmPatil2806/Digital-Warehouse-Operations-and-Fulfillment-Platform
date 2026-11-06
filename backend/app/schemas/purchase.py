"""Requests and responses for supplier purchase orders."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.common import Page
from app.schemas.inventory import ProductRef, UserRef
from app.schemas.order import WarehouseRef


# ============================================================================ requests
class PurchaseOrderLine(BaseModel):
    product_id: int
    quantity: Annotated[int, Field(ge=1, le=1_000_000)]
    # Leave empty to use the supplier's price (or the product's purchase cost).
    unit_cost: Annotated[Decimal | None, Field(ge=0, max_digits=12, decimal_places=2)] = None


def _one_line_per_product(lines: list[PurchaseOrderLine]) -> None:
    ids = [line.product_id for line in lines]
    if len(ids) != len(set(ids)):
        raise ValueError("each product may appear only once")


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    # Default: today + the supplier's (longest product) lead time.
    expected_date: date | None = None
    notes: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    items: Annotated[list[PurchaseOrderLine], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def _check_lines(self) -> "PurchaseOrderCreate":
        _one_line_per_product(self.items)
        return self


class ReceivedLine(BaseModel):
    product_id: int
    quantity: Annotated[int, Field(ge=1, le=1_000_000)]
    bin_id: int


class PurchaseOrderReceipt(BaseModel):
    items: Annotated[list[ReceivedLine], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def _one_line_per_product_and_bin(self) -> "PurchaseOrderReceipt":
        keys = [(line.product_id, line.bin_id) for line in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("each product and bin may appear only once")
        return self


# =========================================================================== responses
class SupplierRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class PurchaseOrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product: ProductRef
    quantity: int
    unit_cost: Decimal
    quantity_received: int
    quantity_outstanding: int


class PurchaseOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    po_number: str
    supplier: SupplierRef
    warehouse: WarehouseRef
    status: str
    expected_date: date
    is_overdue: bool
    notes: str | None
    total_cost: Decimal
    created_by: UserRef | None
    created_at: datetime
    ordered_at: datetime | None
    received_at: datetime | None
    items: list[PurchaseOrderItemResponse]


PurchaseOrderPage = Page[PurchaseOrderResponse]
