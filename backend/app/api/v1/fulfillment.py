"""Picking and packing work queues (admin, manager, staff)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession
from app.api.v1.access import WarehouseReader
from app.core.permissions import require_roles
from app.models.fulfillment import PackingTask, PackingTaskStatus, PickingTaskStatus
from app.models.user import RoleName
from app.repositories.order_repository import OrderRepository
from app.schemas.fulfillment import (
    OrderRef,
    PackConfirmation,
    PackingLine,
    PackingTaskPage,
    PackingTaskResponse,
    PickConfirmation,
    PickingTaskPage,
    PickingTaskResponse,
)
from app.schemas.inventory import ProductRef, UserRef
from app.services.fulfillment_service import FulfillmentService

router = APIRouter(
    tags=["Fulfillment"],
    dependencies=[Depends(require_roles(RoleName.MANAGER, RoleName.STAFF))],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Warehouse role required"},
        404: {"description": "Task not found"},
        409: {"description": "Not possible in the task's current status"},
        422: {"description": "Wrong scan or counts"},
    },
)

OPEN = "open"


def packing_response(task: PackingTask) -> PackingTaskResponse:
    return PackingTaskResponse(
        id=task.id,
        order=OrderRef.model_validate(task.order),
        status=task.status,
        packed_by=UserRef.model_validate(task.packed_by) if task.packed_by else None,
        started_at=task.started_at,
        completed_at=task.completed_at,
        package_count=task.package_count,
        weight_kg=task.weight_kg,
        note=task.note,
        lines=[
            PackingLine(
                product=ProductRef.model_validate(item.product),
                quantity_ordered=item.quantity,
                quantity_picked=item.quantity_picked,
            )
            for item in task.order.items
            if item.quantity_picked
        ],
    )


# ---------------------------------------------------------------------------- picking
@router.get(
    "/picking-tasks",
    response_model=PickingTaskPage,
    summary="Picking work queue: urgent orders first, then along each order's route",
)
def list_picking_tasks(
    db: DbSession,
    user: WarehouseReader,
    status_: Annotated[
        Literal["open", "pending", "in_progress", "completed", "short", "cancelled"],
        Query(alias="status", description="open = pending or in progress"),
    ] = OPEN,
    order_id: int | None = None,
    mine: Annotated[bool, Query(description="Only tasks I started")] = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PickingTaskPage:
    statuses = (
        [PickingTaskStatus.PENDING.value, PickingTaskStatus.IN_PROGRESS.value]
        if status_ == OPEN
        else [status_]
    )
    items, total = OrderRepository(db).picking_queue(
        offset=offset,
        limit=limit,
        statuses=statuses,
        order_id=order_id,
        assigned_to_id=user.id if mine else None,
    )
    return PickingTaskPage(
        items=[PickingTaskResponse.model_validate(t) for t in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/picking-tasks/{task_id}/start", response_model=PickingTaskResponse, summary="Start picking"
)
def start_picking(task_id: int, db: DbSession, user: WarehouseReader) -> PickingTaskResponse:
    return PickingTaskResponse.model_validate(FulfillmentService(db).start(task_id, user=user))


@router.post(
    "/picking-tasks/{task_id}/complete",
    response_model=PickingTaskResponse,
    summary="Confirm a pick with the scanned bin and product",
)
def complete_picking(
    task_id: int, data: PickConfirmation, db: DbSession, user: WarehouseReader
) -> PickingTaskResponse:
    task = FulfillmentService(db).complete(task_id, data, user=user)
    return PickingTaskResponse.model_validate(task)


# ---------------------------------------------------------------------------- packing
@router.get("/packing-tasks", response_model=PackingTaskPage, summary="Packing work queue")
def list_packing_tasks(
    db: DbSession,
    status_: Annotated[
        Literal["open", "pending", "in_progress", "completed"], Query(alias="status")
    ] = OPEN,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PackingTaskPage:
    statuses = (
        [PackingTaskStatus.PENDING.value, PackingTaskStatus.IN_PROGRESS.value]
        if status_ == OPEN
        else [status_]
    )
    items, total = OrderRepository(db).packing_queue(offset=offset, limit=limit, statuses=statuses)
    return PackingTaskPage(
        items=[packing_response(t) for t in items], total=total, offset=offset, limit=limit
    )


@router.post(
    "/packing-tasks/{task_id}/start", response_model=PackingTaskResponse, summary="Start packing"
)
def start_packing(task_id: int, db: DbSession, user: WarehouseReader) -> PackingTaskResponse:
    return packing_response(FulfillmentService(db).start_packing(task_id, user=user))


@router.post(
    "/packing-tasks/{task_id}/complete",
    response_model=PackingTaskResponse,
    summary="Confirm what went into the parcels",
)
def complete_packing(
    task_id: int, data: PackConfirmation, db: DbSession, user: WarehouseReader
) -> PackingTaskResponse:
    return packing_response(FulfillmentService(db).complete_packing(task_id, data, user=user))
