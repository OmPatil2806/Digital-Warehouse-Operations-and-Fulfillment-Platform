"""Supplier purchase orders.

| Action                                   | Who                   |
|------------------------------------------|-----------------------|
| List and read                            | admin, manager, staff |
| Draft, send (order), cancel, check overdue | admin, manager      |
| Receive goods into bins                  | admin, manager, staff |
"""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.api.v1.access import MasterDataEditor, WarehouseReader
from app.models.purchase import PurchaseOrder, PurchaseOrderStatus
from app.schemas.purchase import (
    PurchaseOrderCreate,
    PurchaseOrderPage,
    PurchaseOrderReceipt,
    PurchaseOrderResponse,
)
from app.services.purchase_order_service import PurchaseOrderService

router = APIRouter(
    prefix="/purchase-orders",
    tags=["Purchase orders"],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not allowed"},
        404: {"description": "Not found"},
        409: {"description": "Not possible in the current status"},
    },
)

ManagerUser = MasterDataEditor  # admins and managers


def po_response(po: PurchaseOrder) -> PurchaseOrderResponse:
    return PurchaseOrderResponse.model_validate(po)


@router.get("", response_model=PurchaseOrderPage, summary="List purchase orders")
def list_purchase_orders(
    db: DbSession,
    _: WarehouseReader,
    status_: Annotated[PurchaseOrderStatus | None, Query(alias="status")] = None,
    supplier_id: int | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    overdue: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PurchaseOrderPage:
    items, total = PurchaseOrderService(db).search(
        offset=offset,
        limit=limit,
        status=status_,
        supplier_id=supplier_id,
        q=q,
        overdue=overdue,
    )
    return PurchaseOrderPage(
        items=[po_response(po) for po in items], total=total, offset=offset, limit=limit
    )


@router.post(
    "",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Draft a purchase order",
)
def create_purchase_order(
    data: PurchaseOrderCreate, db: DbSession, user: ManagerUser
) -> PurchaseOrderResponse:
    return po_response(PurchaseOrderService(db).create(data, user=user))


@router.post(
    "/check-overdue",
    response_model=list[PurchaseOrderResponse],
    summary="Raise alerts for purchase orders past their expected date",
)
def check_overdue(db: DbSession, _: ManagerUser) -> list[PurchaseOrderResponse]:
    return [po_response(po) for po in PurchaseOrderService(db).check_overdue()]


@router.get("/{po_id}", response_model=PurchaseOrderResponse, summary="Get a purchase order")
def get_purchase_order(po_id: int, db: DbSession, _: WarehouseReader) -> PurchaseOrderResponse:
    return po_response(PurchaseOrderService(db).get(po_id))


@router.post(
    "/{po_id}/order",
    response_model=PurchaseOrderResponse,
    summary="Send the order to the supplier",
)
def order_purchase_order(po_id: int, db: DbSession, user: ManagerUser) -> PurchaseOrderResponse:
    return po_response(PurchaseOrderService(db).order(po_id, user=user))


@router.post("/{po_id}/cancel", response_model=PurchaseOrderResponse, summary="Cancel")
def cancel_purchase_order(po_id: int, db: DbSession, user: ManagerUser) -> PurchaseOrderResponse:
    return po_response(PurchaseOrderService(db).cancel(po_id, user=user))


@router.post(
    "/{po_id}/receive",
    response_model=PurchaseOrderResponse,
    summary="Receive goods into bins",
)
def receive_purchase_order(
    po_id: int, data: PurchaseOrderReceipt, db: DbSession, user: WarehouseReader
) -> PurchaseOrderResponse:
    return po_response(PurchaseOrderService(db).receive(po_id, data, user=user))
