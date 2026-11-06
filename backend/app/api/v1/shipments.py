"""Carriers, shipments and tracking. Customers see their own shipments."""

from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.v1.access import MasterDataEditor, WarehouseReader, customer_scope, visible_order
from app.models.shipment import Carrier, ShipmentStatus
from app.repositories.order_repository import OrderRepository
from app.schemas.fulfillment import (
    CarrierResponse,
    ShipmentCreate,
    ShipmentEventCreate,
    ShipmentEventResponse,
    ShipmentPage,
    ShipmentResponse,
)
from app.services.shipment_service import ShipmentNotFoundError, ShipmentService

router = APIRouter(
    tags=["Shipments"],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not allowed"},
        404: {"description": "Not found"},
        409: {"description": "Not possible in the current status"},
    },
)


class ShipmentRequest(ShipmentCreate):
    order_id: int


def _visible_shipment(db: DbSession, shipment_id: int, user: CurrentUser):  # noqa: ANN202
    shipment = ShipmentService(db).get(shipment_id)
    scope = customer_scope(db, user)
    if scope is not None and shipment.order.customer_id != scope:
        raise ShipmentNotFoundError()
    return shipment


@router.get("/carriers", response_model=list[CarrierResponse], summary="Active carriers")
def list_carriers(db: DbSession, _: CurrentUser) -> list[CarrierResponse]:
    carriers = db.scalars(
        select(Carrier).where(Carrier.is_active.is_(True)).order_by(Carrier.code)
    ).all()
    return [CarrierResponse.model_validate(c) for c in carriers]


@router.get("/shipments", response_model=ShipmentPage, summary="List shipments (newest first)")
def list_shipments(
    db: DbSession,
    user: CurrentUser,
    status_: Annotated[ShipmentStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=60, description="Tracking or order number")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ShipmentPage:
    items, total = OrderRepository(db).search_shipments(
        offset=offset,
        limit=limit,
        status=status_,
        customer_id=customer_scope(db, user),
        q=q,
    )
    return ShipmentPage(
        items=[ShipmentResponse.model_validate(s) for s in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/shipments",
    response_model=ShipmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ship a packed order",
)
def create_shipment(
    data: ShipmentRequest, db: DbSession, user: WarehouseReader
) -> ShipmentResponse:
    shipment = ShipmentService(db).create(
        data.order_id, ShipmentCreate(**data.model_dump(exclude={"order_id"})), user=user
    )
    return ShipmentResponse.model_validate(shipment)


@router.post(
    "/shipments/check-delays",
    response_model=list[ShipmentResponse],
    summary="Mark shipments past their expected delivery date as delayed",
)
def check_delays(db: DbSession, _: MasterDataEditor) -> list[ShipmentResponse]:
    return [ShipmentResponse.model_validate(s) for s in ShipmentService(db).mark_overdue()]


@router.get("/shipments/{shipment_id}", response_model=ShipmentResponse, summary="Get")
def get_shipment(shipment_id: int, db: DbSession, user: CurrentUser) -> ShipmentResponse:
    return ShipmentResponse.model_validate(_visible_shipment(db, shipment_id, user))


@router.get(
    "/shipments/{shipment_id}/events",
    response_model=list[ShipmentEventResponse],
    summary="Tracking timeline",
)
def shipment_events(
    shipment_id: int, db: DbSession, user: CurrentUser
) -> list[ShipmentEventResponse]:
    shipment = _visible_shipment(db, shipment_id, user)
    return [ShipmentEventResponse.model_validate(e) for e in shipment.events]


@router.post(
    "/shipments/{shipment_id}/events",
    response_model=ShipmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a tracking event (in transit, delayed, delivered, ...)",
)
def add_shipment_event(
    shipment_id: int, data: ShipmentEventCreate, db: DbSession, user: WarehouseReader
) -> ShipmentResponse:
    service = ShipmentService(db)
    service.add_event(shipment_id, data, user=user)
    return ShipmentResponse.model_validate(service.get(shipment_id))


@router.get(
    "/orders/{order_id}/shipment",
    response_model=ShipmentResponse | None,
    summary="The order's shipment (null if not shipped yet)",
)
def order_shipment(order_id: int, db: DbSession, user: CurrentUser) -> ShipmentResponse | None:
    visible_order(db, order_id, user)
    shipment = ShipmentService(db).for_order(order_id)
    return ShipmentResponse.model_validate(shipment) if shipment else None
