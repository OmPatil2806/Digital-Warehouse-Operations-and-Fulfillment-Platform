"""Customer returns. Customers open returns for their own orders; staff inspect them."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.api.v1.access import (
    WarehouseReader,
    customer_scope,
    require_manager_or_owner,
    visible_order,
)
from app.models.order import Return, ReturnStatus
from app.models.user import RoleName
from app.repositories.order_repository import OrderRepository
from app.schemas.fulfillment import ReturnCreate, ReturnInspection
from app.schemas.inventory import BinRef, ProductRef
from app.schemas.order import ReturnItemResponse, ReturnPage, ReturnResponse
from app.services.return_service import ReturnNotFoundError, ReturnService

router = APIRouter(
    prefix="/returns",
    tags=["Returns"],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not allowed"},
        404: {"description": "Not found"},
        409: {"description": "Not possible in the current status"},
    },
)


class ReturnRequest(ReturnCreate):
    order_id: int


def return_response(ret: Return) -> ReturnResponse:
    return ReturnResponse(
        id=ret.id,
        return_number=ret.return_number,
        order_id=ret.order_id,
        order_number=ret.order.order_number,
        status=ret.status,
        reason=ret.reason,
        created_at=ret.created_at,
        completed_at=ret.completed_at,
        items=[
            ReturnItemResponse(
                id=item.id,
                product=ProductRef.model_validate(item.order_item.product),
                quantity=item.quantity,
                condition=item.condition,
                bin=BinRef.model_validate(item.bin) if item.bin else None,
                note=item.note,
            )
            for item in ret.items
        ],
    )


def _visible_return(db: DbSession, return_id: int, user: CurrentUser) -> Return:
    ret = ReturnService(db).get(return_id)
    scope = customer_scope(db, user)
    if scope is not None and ret.order.customer_id != scope:
        raise ReturnNotFoundError()
    return ret


@router.get("", response_model=ReturnPage, summary="List returns (customers: their own)")
def list_returns(
    db: DbSession,
    user: CurrentUser,
    status_: Annotated[ReturnStatus | None, Query(alias="status")] = None,
    order_id: int | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ReturnPage:
    items, total = OrderRepository(db).search_returns(
        offset=offset,
        limit=limit,
        status=status_,
        customer_id=customer_scope(db, user),
        order_id=order_id,
    )
    return ReturnPage(
        items=[return_response(r) for r in items], total=total, offset=offset, limit=limit
    )


@router.post(
    "",
    response_model=ReturnResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a return for a delivered order",
)
def open_return(data: ReturnRequest, db: DbSession, user: CurrentUser) -> ReturnResponse:
    order = visible_order(db, data.order_id, user)
    if not user.has_role(RoleName.STAFF):
        require_manager_or_owner(db, order, user)
    ret = ReturnService(db).open(
        order.id, ReturnCreate(**data.model_dump(exclude={"order_id"})), user=user
    )
    return return_response(ret)


@router.get("/{return_id}", response_model=ReturnResponse, summary="Get a return")
def get_return(return_id: int, db: DbSession, user: CurrentUser) -> ReturnResponse:
    return return_response(_visible_return(db, return_id, user))


@router.post("/{return_id}/inspect", response_model=ReturnResponse, summary="Receive and inspect")
def inspect_return(
    return_id: int, data: ReturnInspection, db: DbSession, user: WarehouseReader
) -> ReturnResponse:
    return return_response(ReturnService(db).inspect(return_id, data, user=user))


@router.post("/{return_id}/cancel", response_model=ReturnResponse, summary="Cancel an open return")
def cancel_return(return_id: int, db: DbSession, user: CurrentUser) -> ReturnResponse:
    ret = _visible_return(db, return_id, user)
    require_manager_or_owner(db, ret.order, user)
    return return_response(ReturnService(db).cancel(ret.id, user=user))
