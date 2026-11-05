"""Inventory endpoints: stock, movements, receiving, adjustments, transfers, reservations.

| Action                                   | Who                                       |
|------------------------------------------|-------------------------------------------|
| Read stock, movements, documents         | admin, manager, staff                     |
| Receive goods                            | admin, manager, staff                     |
| Adjust / transfer                        | admin, manager, staff (*)                 |
| Approve / reject requests, approval queue| admin, manager (never their own request)  |
| Cancel a pending request                 | the person who made it                    |
| Manual reservations (reserve / release)  | admin, manager                            |

(*) Staff adjustments that lose stock and staff transfers to another warehouse become
pending requests (`"applied": false`); see `app/services/approval_service.py`.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession
from app.api.v1.access import MasterDataEditor, WarehouseReader
from app.core.permissions import require_roles
from app.exceptions import NotFoundError
from app.models.catalog import Product
from app.models.inventory import (
    DocumentStatus,
    MovementType,
    ReferenceType,
    ReservationStatus,
    StockAdjustment,
    StockTransfer,
)
from app.models.user import RoleName
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import (
    AdjustmentPage,
    AdjustmentRequest,
    AdjustmentResponse,
    AdjustmentSubmitResponse,
    ApprovalQueueResponse,
    DecisionRequest,
    InventoryPage,
    InventoryResponse,
    MovementPage,
    MovementResponse,
    ProductRef,
    ProductStockResponse,
    ReceiveRequest,
    RejectRequest,
    ReleaseRequest,
    ReservationPage,
    ReservationResponse,
    ReserveRequest,
    TransferPage,
    TransferRequest,
    TransferResponse,
    TransferSubmitResponse,
)
from app.services.alert_service import AlertService
from app.services.approval_service import ApprovalService
from app.services.inventory_service import InventoryService

StockApprover = MasterDataEditor  # managers (and admins)

router = APIRouter(
    prefix="/inventory",
    tags=["Inventory"],
    dependencies=[Depends(require_roles(RoleName.MANAGER, RoleName.STAFF))],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Warehouse role required (or not allowed for this action)"},
    },
)

STOCK_ERRORS = {
    409: {"description": "Not enough stock, bin full, or changed by someone else (retry)"},
    422: {"description": "Invalid input, unknown or archived product/bin"},
}
NOT_FOUND = {404: {"description": "Not found"}}

Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=200)]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


# =================================================================== stock (read)
@router.get("", response_model=InventoryPage, summary="List stock per product and bin")
def list_inventory(
    db: DbSession,
    q: Annotated[str | None, Query(max_length=100, description="SKU, name or bin code")] = None,
    product_id: int | None = None,
    bin_id: int | None = None,
    warehouse_id: int | None = None,
    zone_id: int | None = None,
    include_empty: Annotated[bool, Query(description="Also rows with nothing on hand")] = False,
    offset: Offset = 0,
    limit: Limit = 50,
) -> InventoryPage:
    rows, total = InventoryRepository(db).search_inventory(
        offset=offset,
        limit=limit,
        q=q,
        product_id=product_id,
        bin_id=bin_id,
        warehouse_id=warehouse_id,
        zone_id=zone_id,
        include_empty=include_empty,
    )
    return InventoryPage(
        items=[InventoryResponse.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/products/{product_id}",
    response_model=ProductStockResponse,
    summary="Stock of one product: totals and the bins that hold it",
    responses=NOT_FOUND,
)
def product_stock(product_id: int, db: DbSession) -> ProductStockResponse:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found")
    rows = InventoryRepository(db).rows_for_product(product_id)
    available = AlertService(db).available_quantity(product_id)
    return ProductStockResponse(
        product=ProductRef.model_validate(product),
        min_stock=product.min_stock,
        quantity_on_hand=sum(r.quantity_on_hand for r in rows),
        quantity_reserved=sum(r.quantity_reserved for r in rows),
        quantity_damaged=sum(r.quantity_damaged for r in rows),
        quantity_available=available,
        is_low_stock=product.min_stock > 0 and available < product.min_stock,
        bins=[InventoryResponse.model_validate(r) for r in rows],
    )


@router.get("/movements", response_model=MovementPage, summary="Movement history (newest first)")
def list_movements(
    db: DbSession,
    product_id: int | None = None,
    bin_id: int | None = None,
    movement_type: MovementType | None = None,
    reference_type: ReferenceType | None = None,
    reference_id: int | None = None,
    created_by_id: int | None = None,
    since: Annotated[datetime | None, Query(description="From (inclusive), UTC if no zone")] = None,
    until: Annotated[datetime | None, Query(description="Until (exclusive)")] = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> MovementPage:
    items, total = InventoryRepository(db).search_movements(
        offset=offset,
        limit=limit,
        product_id=product_id,
        bin_id=bin_id,
        movement_type=movement_type,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_id=created_by_id,
        since=_as_utc(since),
        until=_as_utc(until),
    )
    return MovementPage(
        items=[MovementResponse.model_validate(m) for m in items],
        total=total,
        offset=offset,
        limit=limit,
    )


# ======================================================================= receive
@router.post(
    "/receive",
    response_model=InventoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Receive goods into a bin",
    responses=STOCK_ERRORS,
)
def receive(data: ReceiveRequest, db: DbSession, user: WarehouseReader) -> InventoryResponse:
    result = InventoryService(db).receive(data, user=user)
    return InventoryResponse.model_validate(result.inventory)


# =================================================================== adjustments
@router.post(
    "/adjustments",
    response_model=AdjustmentSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Adjust stock (found, lost, damaged, restored, written off)",
    responses=STOCK_ERRORS,
)
def adjust(
    data: AdjustmentRequest, db: DbSession, user: WarehouseReader
) -> AdjustmentSubmitResponse:
    result = ApprovalService(db).submit_adjustment(data, user=user)
    return AdjustmentSubmitResponse(
        applied=result.applied, adjustment=AdjustmentResponse.model_validate(result.document)
    )


@router.get("/adjustments", response_model=AdjustmentPage, summary="List adjustments")
def list_adjustments(
    db: DbSession,
    user: WarehouseReader,
    status_: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    product_id: int | None = None,
    mine: Annotated[bool, Query(description="Only my own requests")] = False,
    offset: Offset = 0,
    limit: Limit = 50,
) -> AdjustmentPage:
    items, total = InventoryRepository(db).search_documents(
        StockAdjustment,
        offset=offset,
        limit=limit,
        status=status_,
        product_id=product_id,
        requested_by_id=user.id if mine else None,
    )
    return AdjustmentPage(
        items=[AdjustmentResponse.model_validate(a) for a in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/adjustments/{adjustment_id}/approve",
    response_model=AdjustmentResponse,
    summary="Approve a pending adjustment (applies it)",
    responses={**STOCK_ERRORS, **NOT_FOUND},
)
def approve_adjustment(
    adjustment_id: int, db: DbSession, user: StockApprover, data: DecisionRequest | None = None
) -> AdjustmentResponse:
    service = ApprovalService(db)
    document = service.get(StockAdjustment, adjustment_id)
    service.approve(document, approver=user, note=data.note if data else None)
    return AdjustmentResponse.model_validate(document)


@router.post(
    "/adjustments/{adjustment_id}/reject",
    response_model=AdjustmentResponse,
    summary="Reject a pending adjustment",
    responses={409: STOCK_ERRORS[409], **NOT_FOUND},
)
def reject_adjustment(
    adjustment_id: int, data: RejectRequest, db: DbSession, user: StockApprover
) -> AdjustmentResponse:
    service = ApprovalService(db)
    document = service.reject(
        service.get(StockAdjustment, adjustment_id), approver=user, note=data.note
    )
    return AdjustmentResponse.model_validate(document)


@router.post(
    "/adjustments/{adjustment_id}/cancel",
    response_model=AdjustmentResponse,
    summary="Withdraw your own pending adjustment",
    responses=NOT_FOUND,
)
def cancel_adjustment(
    adjustment_id: int, db: DbSession, user: WarehouseReader
) -> AdjustmentResponse:
    service = ApprovalService(db)
    document = service.cancel(service.get(StockAdjustment, adjustment_id), user=user)
    return AdjustmentResponse.model_validate(document)


# ===================================================================== transfers
@router.post(
    "/transfers",
    response_model=TransferSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Move stock to another bin",
    responses=STOCK_ERRORS,
)
def transfer(data: TransferRequest, db: DbSession, user: WarehouseReader) -> TransferSubmitResponse:
    result = ApprovalService(db).submit_transfer(data, user=user)
    return TransferSubmitResponse(
        applied=result.applied, transfer=TransferResponse.model_validate(result.document)
    )


@router.get("/transfers", response_model=TransferPage, summary="List transfers")
def list_transfers(
    db: DbSession,
    user: WarehouseReader,
    status_: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    product_id: int | None = None,
    mine: Annotated[bool, Query(description="Only my own requests")] = False,
    offset: Offset = 0,
    limit: Limit = 50,
) -> TransferPage:
    items, total = InventoryRepository(db).search_documents(
        StockTransfer,
        offset=offset,
        limit=limit,
        status=status_,
        product_id=product_id,
        requested_by_id=user.id if mine else None,
    )
    return TransferPage(
        items=[TransferResponse.model_validate(t) for t in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/transfers/{transfer_id}/approve",
    response_model=TransferResponse,
    summary="Approve a pending transfer (moves the stock)",
    responses={**STOCK_ERRORS, **NOT_FOUND},
)
def approve_transfer(
    transfer_id: int, db: DbSession, user: StockApprover, data: DecisionRequest | None = None
) -> TransferResponse:
    service = ApprovalService(db)
    document = service.get(StockTransfer, transfer_id)
    service.approve(document, approver=user, note=data.note if data else None)
    return TransferResponse.model_validate(document)


@router.post(
    "/transfers/{transfer_id}/reject",
    response_model=TransferResponse,
    summary="Reject a pending transfer",
    responses={409: STOCK_ERRORS[409], **NOT_FOUND},
)
def reject_transfer(
    transfer_id: int, data: RejectRequest, db: DbSession, user: StockApprover
) -> TransferResponse:
    service = ApprovalService(db)
    document = service.reject(
        service.get(StockTransfer, transfer_id), approver=user, note=data.note
    )
    return TransferResponse.model_validate(document)


@router.post(
    "/transfers/{transfer_id}/cancel",
    response_model=TransferResponse,
    summary="Withdraw your own pending transfer",
    responses=NOT_FOUND,
)
def cancel_transfer(transfer_id: int, db: DbSession, user: WarehouseReader) -> TransferResponse:
    service = ApprovalService(db)
    document = service.cancel(service.get(StockTransfer, transfer_id), user=user)
    return TransferResponse.model_validate(document)


@router.get(
    "/approvals",
    response_model=ApprovalQueueResponse,
    summary="Requests waiting for a manager (oldest first)",
)
def approval_queue(db: DbSession, _user: StockApprover) -> ApprovalQueueResponse:
    pending = ApprovalService(db).pending()
    return ApprovalQueueResponse(
        adjustments=[
            AdjustmentResponse.model_validate(d) for d in pending if isinstance(d, StockAdjustment)
        ],
        transfers=[
            TransferResponse.model_validate(d) for d in pending if isinstance(d, StockTransfer)
        ],
    )


# ================================================================== reservations
@router.post(
    "/reservations",
    response_model=list[ReservationResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Reserve stock (one reservation per bin used)",
    responses=STOCK_ERRORS,
)
def reserve(data: ReserveRequest, db: DbSession, user: StockApprover) -> list[ReservationResponse]:
    result = InventoryService(db).reserve(data, user=user)
    return [ReservationResponse.model_validate(r) for r in result.reservations]


@router.get("/reservations", response_model=ReservationPage, summary="List reservations")
def list_reservations(
    db: DbSession,
    status_: Annotated[ReservationStatus | None, Query(alias="status")] = None,
    product_id: int | None = None,
    reference_type: ReferenceType | None = None,
    reference_id: int | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> ReservationPage:
    items, total = InventoryRepository(db).search_reservations(
        offset=offset,
        limit=limit,
        status=status_,
        product_id=product_id,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    return ReservationPage(
        items=[ReservationResponse.model_validate(r) for r in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/reservations/{reservation_id}/release",
    response_model=ReservationResponse,
    summary="Release a reservation (units become available again)",
    responses={**NOT_FOUND, 409: {"description": "Reservation is not active"}},
)
def release(
    reservation_id: int, db: DbSession, user: StockApprover, data: ReleaseRequest | None = None
) -> ReservationResponse:
    reservation = InventoryService(db).release(reservation_id, data, user=user)
    return ReservationResponse.model_validate(reservation)
