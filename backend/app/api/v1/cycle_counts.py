"""Cycle count endpoints.

Staff (and managers/admins) start counts, enter quantities and submit them; a manager or
admin who did not start the count approves (stock corrected) or rejects (recount).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession
from app.api.v1.access import MasterDataEditor, WarehouseReader
from app.core.permissions import require_roles
from app.models.inventory import CycleCountStatus
from app.models.user import RoleName
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import (
    CycleCountPage,
    CycleCountRecord,
    CycleCountResponse,
    CycleCountStart,
    CycleCountSummary,
    DecisionRequest,
    RejectRequest,
)
from app.services.cycle_count_service import CycleCountService

router = APIRouter(
    prefix="/cycle-counts",
    tags=["Cycle counts"],
    dependencies=[Depends(require_roles(RoleName.MANAGER, RoleName.STAFF))],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Warehouse role required (or not allowed for this action)"},
        404: {"description": "Cycle count not found"},
        409: {"description": "Not allowed in the count's current status"},
    },
)


@router.get("", response_model=CycleCountPage, summary="List cycle counts (newest first)")
def list_cycle_counts(
    db: DbSession,
    status_: Annotated[CycleCountStatus | None, Query(alias="status")] = None,
    bin_id: int | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CycleCountPage:
    items, total = InventoryRepository(db).search_cycle_counts(
        offset=offset, limit=limit, status=status_, bin_id=bin_id
    )
    return CycleCountPage(
        items=[CycleCountSummary.model_validate(c) for c in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "",
    response_model=CycleCountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start counting a bin",
)
def start_cycle_count(
    data: CycleCountStart, db: DbSession, user: WarehouseReader
) -> CycleCountResponse:
    return CycleCountResponse.model_validate(CycleCountService(db).start(data, user=user))


@router.get("/{count_id}", response_model=CycleCountResponse, summary="Get a cycle count")
def get_cycle_count(count_id: int, db: DbSession) -> CycleCountResponse:
    return CycleCountResponse.model_validate(CycleCountService(db).get(count_id))


@router.put(
    "/{count_id}/lines",
    response_model=CycleCountResponse,
    summary="Enter counted quantities (while the count is open)",
)
def record_counts(
    count_id: int, data: CycleCountRecord, db: DbSession, user: WarehouseReader
) -> CycleCountResponse:
    return CycleCountResponse.model_validate(
        CycleCountService(db).record(count_id, data, user=user)
    )


@router.post("/{count_id}/submit", response_model=CycleCountResponse, summary="Submit for approval")
def submit_count(count_id: int, db: DbSession, user: WarehouseReader) -> CycleCountResponse:
    return CycleCountResponse.model_validate(CycleCountService(db).submit(count_id, user=user))


@router.post(
    "/{count_id}/approve",
    response_model=CycleCountResponse,
    summary="Approve: apply the differences to the stock",
)
def approve_count(
    count_id: int, db: DbSession, user: MasterDataEditor, data: DecisionRequest | None = None
) -> CycleCountResponse:
    count = CycleCountService(db).approve(count_id, approver=user, note=data.note if data else None)
    return CycleCountResponse.model_validate(count)


@router.post(
    "/{count_id}/reject", response_model=CycleCountResponse, summary="Send back for a recount"
)
def reject_count(
    count_id: int, data: RejectRequest, db: DbSession, user: MasterDataEditor
) -> CycleCountResponse:
    count = CycleCountService(db).reject(count_id, approver=user, note=data.note)
    return CycleCountResponse.model_validate(count)


@router.post("/{count_id}/cancel", response_model=CycleCountResponse, summary="Cancel a count")
def cancel_count(count_id: int, db: DbSession, user: WarehouseReader) -> CycleCountResponse:
    return CycleCountResponse.model_validate(CycleCountService(db).cancel(count_id, user=user))
