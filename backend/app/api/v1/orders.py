"""Order endpoints. See the permission table in app/api/v1/access.py."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.api.v1.access import (
    MasterDataEditor,
    WarehouseReader,
    customer_scope,
    require_manager_or_owner,
    visible_order,
)
from app.exceptions import PermissionDeniedError
from app.models.order import Order, OrderStatus
from app.models.user import RoleName
from app.repositories.order_repository import OrderRepository
from app.schemas.fulfillment import PickingTaskResponse
from app.schemas.order import (
    OrderCreate,
    OrderPage,
    OrderResponse,
    OrderSummary,
    ReasonRequest,
    StatusNote,
)
from app.services.fulfillment_service import FulfillmentService
from app.services.order_service import OrderService, statuses_reachable_from

router = APIRouter(
    prefix="/orders",
    tags=["Orders"],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not allowed"},
        404: {"description": "Order not found"},
        409: {"description": "Not possible in the order's current status"},
    },
)


def order_response(order: Order) -> OrderResponse:
    response = OrderResponse.model_validate(order)
    response.next_statuses = [s.value for s in statuses_reachable_from(OrderStatus(order.status))]
    return response


@router.get("", response_model=OrderPage, summary="List orders (customers: their own)")
def list_orders(
    db: DbSession,
    user: CurrentUser,
    q: Annotated[str | None, Query(max_length=100, description="Order number or customer")] = None,
    status_: Annotated[OrderStatus | None, Query(alias="status")] = None,
    customer_id: int | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> OrderPage:
    scope = customer_scope(db, user)
    items, total = OrderRepository(db).search_orders(
        offset=offset,
        limit=limit,
        q=q,
        status=status_,
        customer_id=scope if scope is not None else customer_id,
    )
    return OrderPage(
        items=[OrderSummary.model_validate(o) for o in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order (customers for themselves, managers for any customer)",
)
def create_order(data: OrderCreate, db: DbSession, user: CurrentUser) -> OrderResponse:
    manager = user.has_role(RoleName.ADMIN, RoleName.MANAGER)
    if not manager and (
        user.has_role(RoleName.STAFF) or customer_scope(db, user) != data.customer_id
    ):
        raise PermissionDeniedError("You can only place orders for your own customer account")
    return order_response(OrderService(db).create(data, user=user))


@router.get("/{order_id}", response_model=OrderResponse, summary="Get an order")
def get_order(order_id: int, db: DbSession, user: CurrentUser) -> OrderResponse:
    return order_response(visible_order(db, order_id, user))


@router.post("/{order_id}/confirm", response_model=OrderResponse, summary="Confirm and reserve")
def confirm_order(
    order_id: int, db: DbSession, user: CurrentUser, data: StatusNote | None = None
) -> OrderResponse:
    require_manager_or_owner(db, visible_order(db, order_id, user), user)
    order = OrderService(db).confirm(order_id, user=user, note=data.note if data else None)
    return order_response(order)


@router.post("/{order_id}/cancel", response_model=OrderResponse, summary="Cancel (before picking)")
def cancel_order(
    order_id: int, data: ReasonRequest, db: DbSession, user: CurrentUser
) -> OrderResponse:
    require_manager_or_owner(db, visible_order(db, order_id, user), user)
    return order_response(OrderService(db).cancel(order_id, user=user, reason=data.reason))


@router.post("/{order_id}/hold", response_model=OrderResponse, summary="Put on hold")
def hold_order(
    order_id: int, data: ReasonRequest, db: DbSession, user: MasterDataEditor
) -> OrderResponse:
    return order_response(OrderService(db).hold(order_id, user=user, reason=data.reason))


@router.post("/{order_id}/release", response_model=OrderResponse, summary="Release the hold")
def release_order(
    order_id: int, db: DbSession, user: MasterDataEditor, data: StatusNote | None = None
) -> OrderResponse:
    order = OrderService(db).release_hold(order_id, user=user, note=data.note if data else None)
    return order_response(order)


@router.post(
    "/{order_id}/reserve", response_model=OrderResponse, summary="Retry reserving missing units"
)
def reserve_order(order_id: int, db: DbSession, user: MasterDataEditor) -> OrderResponse:
    return order_response(OrderService(db).reserve_stock(order_id, user=user))


@router.post(
    "/{order_id}/allocate",
    response_model=list[PickingTaskResponse],
    summary="Create the picking route (reserved -> allocated)",
)
def allocate_order(
    order_id: int, db: DbSession, user: WarehouseReader
) -> list[PickingTaskResponse]:
    tasks = FulfillmentService(db).allocate(order_id, user=user)
    return [PickingTaskResponse.model_validate(t) for t in tasks]


@router.get(
    "/{order_id}/picking-tasks",
    response_model=list[PickingTaskResponse],
    summary="The order's picking tasks in route order",
)
def order_picking_tasks(
    order_id: int, db: DbSession, _: WarehouseReader
) -> list[PickingTaskResponse]:
    tasks = FulfillmentService(db).tasks_for_order(order_id)
    return [PickingTaskResponse.model_validate(t) for t in tasks]
