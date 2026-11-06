"""Tests for shipment tracking, delays and customer returns."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, UnprocessableError
from app.models.audit import Alert
from app.models.catalog import Product
from app.models.inventory import InventoryMovement
from app.models.order import Order, OrderStatus, ReturnStatus
from app.models.shipment import Shipment, ShipmentStatus
from app.models.user import RoleName, User
from app.models.warehouse import Bin
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.fulfillment import (
    PackConfirmation,
    PickConfirmation,
    ReturnCreate,
    ReturnInspection,
    ShipmentCreate,
    ShipmentEventCreate,
)
from app.schemas.inventory import ReceiveRequest
from app.schemas.order import OrderCreate
from app.services.fulfillment_service import FulfillmentService
from app.services.inventory_service import InventoryService
from app.services.order_service import OrderService
from app.services.return_service import ReturnService
from app.services.shipment_service import ShipmentService
from tests.factories import (
    create_bin,
    create_carrier,
    create_category,
    create_customer,
    create_product,
    create_user,
)

S = OrderStatus


@pytest.fixture()
def products(db_session: Session) -> list[Product]:
    category = create_category(db_session)
    return [
        create_product(db_session, category, sku="LAP-001"),
        create_product(db_session, category, sku="MOU-001", unit_price=Decimal("24.90")),
    ]


@pytest.fixture()
def staff(db_session: Session) -> User:
    return create_user(
        db_session, "sam@example.com", full_name="Sam Staff", roles=(RoleName.STAFF,)
    )


@pytest.fixture()
def returns_bin(db_session: Session) -> Bin:
    bin_ = create_bin(db_session, "WH01-ZR-R01-S01-B01")
    bin_.shelf.rack.zone.zone_type = "returns"
    db_session.commit()
    return bin_


@pytest.fixture()
def shipment(db_session: Session, products, staff) -> Shipment:
    """A shipped order for 2 LAP + 3 MOU (DHL, expected in 2 working days)."""
    bin_ = create_bin(db_session)
    inventory = InventoryService(db_session)
    for product, quantity in ((products[0], 2), (products[1], 3)):
        inventory.receive(
            ReceiveRequest(product_id=product.id, bin_id=bin_.id, quantity=quantity), user=None
        )
    orders = OrderService(db_session)
    order = orders.create(
        OrderCreate(
            customer_id=create_customer(db_session).id,
            items=[
                {"product_id": products[0].id, "quantity": 2},
                {"product_id": products[1].id, "quantity": 3},
            ],
        ),
        user=None,
    )
    orders.confirm(order.id, user=None)
    fulfillment = FulfillmentService(db_session)
    for task in fulfillment.allocate(order.id, user=None):
        fulfillment.start(task.id, user=staff)
        fulfillment.complete(
            task.id,
            PickConfirmation(
                bin_code=task.bin.location_code,
                product_code=task.product.sku,
                quantity_picked=task.quantity,
            ),
            user=staff,
        )
    packing = fulfillment.packing_task_for_order(order.id)
    fulfillment.start_packing(packing.id, user=staff)
    fulfillment.complete_packing(
        packing.id,
        PackConfirmation(
            items=[
                {"product_id": products[0].id, "quantity": 2},
                {"product_id": products[1].id, "quantity": 3},
            ],
            package_count=1,
            weight_kg="3.5",
        ),
        user=staff,
    )
    carrier = create_carrier(db_session, "DHL", default_transit_days=2)
    return ShipmentService(db_session).create(
        order.id, ShipmentCreate(carrier_id=carrier.id), user=staff
    )


def event(kind: str, **extra: object) -> ShipmentEventCreate:
    return ShipmentEventCreate(event_type=kind, **extra)


# --------------------------------------------------------------------------- tracking
def test_tracking_timeline_until_delivery(db_session: Session, shipment: Shipment, staff):
    service = ShipmentService(db_session)

    service.add_event(shipment.id, event("in_transit", location="Hub Leipzig"), user=staff)
    assert shipment.status == ShipmentStatus.IN_TRANSIT
    service.add_event(shipment.id, event("out_for_delivery", location="Stuttgart"), user=staff)
    service.add_event(shipment.id, event("delivered", location="Front door"), user=staff)

    assert [e.event_type for e in shipment.events] == [
        "dispatched",
        "in_transit",
        "out_for_delivery",
        "delivered",
    ]
    order = shipment.order
    assert shipment.status == ShipmentStatus.DELIVERED
    assert order.status == S.DELIVERED
    assert order.delivered_at == shipment.delivered_at is not None
    assert order.history[-1].note == "Front door"
    with pytest.raises(ConflictError, match="already delivered"):
        service.add_event(shipment.id, event("in_transit"), user=staff)


def test_events_cannot_be_in_the_future_or_before_dispatch(
    db_session: Session, shipment: Shipment, staff
):
    service = ShipmentService(db_session)

    with pytest.raises(UnprocessableError, match="in the future"):
        service.add_event(
            shipment.id,
            event("in_transit", occurred_at=datetime.now(UTC) + timedelta(days=1)),
            user=staff,
        )
    with pytest.raises(UnprocessableError, match="before the shipment was sent"):
        service.add_event(
            shipment.id,
            event("in_transit", occurred_at=shipment.shipped_at - timedelta(hours=2)),
            user=staff,
        )
    with pytest.raises(ValidationError, match="describe the exception"):
        event("exception")
    service.add_event(shipment.id, event("exception", description="Address not found"), user=staff)
    assert shipment.status == ShipmentStatus.DISPATCHED  # recorded only


def test_a_delay_raises_an_alert_that_delivery_resolves(
    db_session: Session, shipment: Shipment, staff
):
    service = ShipmentService(db_session)
    order = shipment.order

    service.add_event(shipment.id, event("delayed", description="Storm in the north"), user=staff)

    assert (shipment.status, order.status) == (ShipmentStatus.DELAYED, S.DELAYED)
    alert = db_session.scalar(select(Alert).where(Alert.alert_type == "delay_risk"))
    assert alert.title == f"Delayed: {order.order_number}"
    assert alert.status == "open" and "Storm in the north" in alert.message

    service.add_event(shipment.id, event("in_transit"), user=staff)
    assert shipment.status == ShipmentStatus.DELAYED  # stays delayed until delivered
    service.add_event(shipment.id, event("delivered"), user=staff)

    db_session.refresh(alert)
    assert alert.status == "resolved"
    assert order.status == S.DELIVERED


def test_overdue_shipments_are_marked_delayed(db_session: Session, shipment: Shipment):
    service = ShipmentService(db_session)

    assert service.mark_overdue(today=shipment.expected_delivery_date) == []  # not late yet
    late = service.mark_overdue(today=shipment.expected_delivery_date + timedelta(days=1))

    assert late == [shipment]
    assert shipment.order.status == S.DELAYED
    assert shipment.events[-1].description == (
        f"Not delivered by {shipment.expected_delivery_date.isoformat()}"
    )
    assert service.mark_overdue(today=date.max) == []  # already delayed: not twice


# ---------------------------------------------------------------------------- returns
def delivered(db_session: Session, shipment: Shipment, staff) -> Order:
    ShipmentService(db_session).add_event(shipment.id, event("delivered"), user=staff)
    return shipment.order


def test_only_delivered_orders_can_be_returned(
    db_session: Session, shipment: Shipment, products, staff
):
    with pytest.raises(ConflictError, match="only delivered orders can be returned"):
        ReturnService(db_session).open(
            shipment.order_id,
            ReturnCreate(
                reason="Wrong size", items=[{"product_id": products[0].id, "quantity": 1}]
            ),
            user=None,
        )


def test_return_restock_and_damaged(
    db_session: Session, shipment: Shipment, products, staff, returns_bin
):
    order = delivered(db_session, shipment, staff)
    service = ReturnService(db_session)

    ret = service.open(
        order.id,
        ReturnCreate(
            reason="Customer changed their mind",
            items=[
                {"product_id": products[0].id, "quantity": 1},
                {"product_id": products[1].id, "quantity": 2},
            ],
        ),
        user=None,
    )
    assert ret.return_number == f"RT-{datetime.now(UTC).year}-000001"
    assert ret.status == ReturnStatus.OPEN

    service.inspect(
        ret.id,
        ReturnInspection(
            items=[
                {"product_id": products[0].id, "condition": "restock"},
                {"product_id": products[1].id, "condition": "damaged", "note": "Box crushed"},
            ]
        ),
        user=staff,
    )

    assert ret.status == ReturnStatus.COMPLETED and ret.inspected_by_id == staff.id
    rows = InventoryRepository(db_session)
    lap = rows.get_row(products[0].id, returns_bin.id)
    mou = rows.get_row(products[1].id, returns_bin.id)
    assert (lap.quantity_on_hand, lap.quantity_damaged, lap.quantity_available) == (1, 0, 1)
    assert (mou.quantity_on_hand, mou.quantity_damaged, mou.quantity_available) == (2, 2, 0)
    movements = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.movement_type == "return")
    ).all()
    assert {(m.reference_type, m.reference_id) for m in movements} == {("return", ret.id)}
    assert [i.quantity_returned for i in order.items] == [1, 2]
    assert order.status == S.RETURNED
    assert order.history[-1].note == f"Return {ret.return_number}: 3 of 5 unit(s) returned"


def test_never_more_returned_than_shipped(
    db_session: Session, shipment: Shipment, products, staff, returns_bin
):
    order = delivered(db_session, shipment, staff)
    service = ReturnService(db_session)
    first = service.open(
        order.id,
        ReturnCreate(reason="Too many", items=[{"product_id": products[1].id, "quantity": 2}]),
        user=None,
    )

    with pytest.raises(
        UnprocessableError, match="MOU-001: only 1 unit\\(s\\) can still be returned"
    ):
        service.open(
            order.id,
            ReturnCreate(reason="Again", items=[{"product_id": products[1].id, "quantity": 2}]),
            user=None,
        )
    stranger = create_product(db_session, products[0].category, sku="XYZ-001")
    with pytest.raises(UnprocessableError, match="not part of this order"):
        service.open(
            order.id,
            ReturnCreate(reason="Odd", items=[{"product_id": stranger.id, "quantity": 1}]),
            user=None,
        )

    service.cancel(first.id, user=None)  # cancelled returns free the units again
    second = service.open(
        order.id,
        ReturnCreate(reason="All of them", items=[{"product_id": products[1].id, "quantity": 3}]),
        user=None,
    )
    assert second.items[0].quantity == 3
    with pytest.raises(ConflictError, match="already cancelled"):
        service.inspect(
            first.id,
            ReturnInspection(items=[{"product_id": products[1].id, "condition": "restock"}]),
            user=staff,
        )


def test_inspection_must_cover_every_line_and_needs_a_bin(
    db_session: Session, shipment: Shipment, products, staff
):
    order = delivered(db_session, shipment, staff)
    service = ReturnService(db_session)
    ret = service.open(
        order.id,
        ReturnCreate(
            reason="Wrong",
            items=[
                {"product_id": products[0].id, "quantity": 1},
                {"product_id": products[1].id, "quantity": 1},
            ],
        ),
        user=None,
    )

    with pytest.raises(UnprocessableError, match="missing: MOU-001"):
        service.inspect(
            ret.id,
            ReturnInspection(items=[{"product_id": products[0].id, "condition": "restock"}]),
            user=staff,
        )
    both = ReturnInspection(
        items=[
            {"product_id": products[0].id, "condition": "restock"},
            {"product_id": products[1].id, "condition": "restock"},
        ]
    )
    with pytest.raises(UnprocessableError, match="No returns-zone bin with room"):
        service.inspect(ret.id, both, user=staff)  # this warehouse has no returns zone

    chosen = create_bin(db_session, "WH01-ZA-R03-S01-B01")
    service.inspect(
        ret.id,
        ReturnInspection(
            items=[
                {"product_id": products[0].id, "condition": "restock", "bin_id": chosen.id},
                {"product_id": products[1].id, "condition": "restock", "bin_id": chosen.id},
            ]
        ),
        user=staff,
    )
    assert {i.bin_id for i in ret.items} == {chosen.id}


def test_restocked_returns_fill_backorders(
    db_session: Session, shipment: Shipment, products, staff, returns_bin
):
    order = delivered(db_session, shipment, staff)
    orders = OrderService(db_session)
    waiting = orders.create(
        OrderCreate(
            customer_id=order.customer_id, items=[{"product_id": products[0].id, "quantity": 1}]
        ),
        user=None,
    )
    orders.confirm(waiting.id, user=None)
    assert waiting.status == S.BACKORDERED
    service = ReturnService(db_session)
    ret = service.open(
        order.id,
        ReturnCreate(reason="Not needed", items=[{"product_id": products[0].id, "quantity": 1}]),
        user=None,
    )

    service.inspect(
        ret.id,
        ReturnInspection(items=[{"product_id": products[0].id, "condition": "restock"}]),
        user=staff,
    )

    db_session.refresh(waiting)
    assert waiting.status == S.INVENTORY_RESERVED
