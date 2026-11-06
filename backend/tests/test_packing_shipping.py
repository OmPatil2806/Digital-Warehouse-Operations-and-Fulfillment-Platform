"""Tests for packing (picked -> packed) and shipping (packed -> shipped)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, UnprocessableError
from app.models.audit import AuditLog
from app.models.catalog import Product
from app.models.fulfillment import PackingTask, PackingTaskStatus
from app.models.order import Customer, Order, OrderStatus
from app.models.shipment import Carrier, ShipmentStatus
from app.models.user import RoleName, User
from app.schemas.fulfillment import PackConfirmation, PickConfirmation, ShipmentCreate
from app.schemas.inventory import ReceiveRequest
from app.schemas.order import OrderCreate
from app.services.fulfillment_service import FulfillmentService
from app.services.inventory_service import InventoryService
from app.services.order_service import InvalidTransitionError, OrderService
from app.services.shipment_service import ShipmentService, add_working_days
from tests.factories import (
    create_bin,
    create_carrier,
    create_category,
    create_customer,
    create_product,
    create_user,
)

S = OrderStatus
P = PackingTaskStatus


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
def carrier(db_session: Session) -> Carrier:
    return create_carrier(db_session, "DHL", default_transit_days=2)


@pytest.fixture()
def fulfillment(db_session: Session) -> FulfillmentService:
    return FulfillmentService(db_session)


@pytest.fixture()
def shipments(db_session: Session) -> ShipmentService:
    return ShipmentService(db_session)


def picked_order(db: Session, products: list[Product], staff: User, *, short: int = 0) -> Order:
    """An order for 2 LAP + 3 MOU, picked completely (or with `short` MOU missing)."""
    bin_ = create_bin(db)
    inventory = InventoryService(db)
    for product, quantity in ((products[0], 2), (products[1], 3)):
        inventory.receive(
            ReceiveRequest(product_id=product.id, bin_id=bin_.id, quantity=quantity), user=None
        )
    orders = OrderService(db)
    customer: Customer = create_customer(db)
    order = orders.create(
        OrderCreate(
            customer_id=customer.id,
            items=[
                {"product_id": products[0].id, "quantity": 2},
                {"product_id": products[1].id, "quantity": 3},
            ],
        ),
        user=None,
    )
    orders.confirm(order.id, user=None)
    service = FulfillmentService(db)
    for task in service.allocate(order.id, user=None):
        service.start(task.id, user=staff)
        missing = short if task.product_id == products[1].id else 0
        service.complete(
            task.id,
            PickConfirmation(
                bin_code=task.bin.location_code,
                product_code=task.product.sku,
                quantity_picked=task.quantity - missing,
                short_reason="Missing" if missing else None,
            ),
            user=staff,
        )
    return order


def pack(products: list[Product], lap: int = 2, mou: int = 3, **extra: object) -> PackConfirmation:
    values: dict[str, object] = {
        "items": [
            {"product_id": products[0].id, "quantity": lap},
            {"product_id": products[1].id, "quantity": mou},
        ],
        "package_count": 2,
        "weight_kg": "7.250",
    }
    values.update(extra)
    return PackConfirmation(**values)


# -------------------------------------------------------------------------- packing
def test_a_packing_task_waits_when_picking_is_done(
    db_session: Session, fulfillment: FulfillmentService, products, staff
):
    order = picked_order(db_session, products, staff)

    assert order.status == S.PICKED
    task = fulfillment.packing_task_for_order(order.id)
    assert task.status == P.PENDING


def test_packing_checks_every_line_against_what_was_picked(
    db_session: Session, fulfillment: FulfillmentService, products, staff
):
    order = picked_order(db_session, products, staff)
    task = fulfillment.packing_task_for_order(order.id)

    with pytest.raises(ConflictError, match="start it before confirming"):
        fulfillment.complete_packing(task.id, pack(products), user=staff)
    fulfillment.start_packing(task.id, user=staff)
    assert order.status == S.PACKING
    assert order.history[-1].note == "Packed by Sam Staff"

    with pytest.raises(UnprocessableError, match="MOU-001: 2 packed, 3 picked"):
        fulfillment.complete_packing(task.id, pack(products, mou=2), user=staff)
    stranger = create_product(db_session, products[0].category, sku="XYZ-001")
    wrong = PackConfirmation(
        items=[
            {"product_id": products[0].id, "quantity": 2},
            {"product_id": products[1].id, "quantity": 3},
            {"product_id": stranger.id, "quantity": 1},
        ],
        package_count=1,
        weight_kg="1",
    )
    with pytest.raises(UnprocessableError, match=f"product {stranger.id} is not part"):
        fulfillment.complete_packing(task.id, wrong, user=staff)
    assert order.status == S.PACKING

    fulfillment.complete_packing(task.id, pack(products, note="Fragile"), user=staff)

    assert (task.status, task.package_count, task.weight_kg) == (P.COMPLETED, 2, Decimal("7.250"))
    assert [i.quantity_packed for i in order.items] == [2, 3]
    assert order.status == S.PACKED
    assert order.history[-1].note == "2 parcel(s), 7.250 kg"


def test_short_picked_lines_are_packed_as_picked(
    db_session: Session, fulfillment: FulfillmentService, products, staff
):
    order = picked_order(db_session, products, staff, short=1)  # 2 of 3 mice picked
    task = fulfillment.packing_task_for_order(order.id)
    fulfillment.start_packing(task.id, user=staff)

    fulfillment.complete_packing(task.id, pack(products, mou=2), user=staff)

    assert [i.quantity_packed for i in order.items] == [2, 2]


def test_an_order_with_nothing_picked_gets_no_packing_and_can_be_cancelled(
    db_session: Session, fulfillment: FulfillmentService, products, staff
):
    category = products[0].category
    lonely = create_product(db_session, category, sku="ONE-001")
    bin_ = create_bin(db_session, "WH01-ZA-R02-S01-B01")
    InventoryService(db_session).receive(
        ReceiveRequest(product_id=lonely.id, bin_id=bin_.id, quantity=1), user=None
    )
    orders = OrderService(db_session)
    order = orders.create(
        OrderCreate(
            customer_id=create_customer(db_session).id,
            items=[{"product_id": lonely.id, "quantity": 1}],
        ),
        user=None,
    )
    orders.confirm(order.id, user=None)
    [task] = fulfillment.allocate(order.id, user=None)
    fulfillment.start(task.id, user=staff)
    fulfillment.complete(
        task.id,
        PickConfirmation(
            bin_code=task.bin.location_code,
            product_code="ONE-001",
            quantity_picked=0,
            short_reason="Bin empty",
        ),
        user=staff,
    )

    assert order.status == S.PICKED
    assert fulfillment.packing_task_for_order(order.id) is None
    orders.cancel(order.id, user=None, reason="Nothing to ship")
    assert order.status == S.CANCELLED


def test_picked_goods_cannot_be_cancelled(db_session: Session, products, staff):
    order = picked_order(db_session, products, staff)

    with pytest.raises(InvalidTransitionError, match="has picked goods"):
        OrderService(db_session).cancel(order.id, user=None, reason="Too late")


# -------------------------------------------------------------------------- shipping
def packed_order(db: Session, products, staff) -> Order:
    order = picked_order(db, products, staff)
    service = FulfillmentService(db)
    task = service.packing_task_for_order(order.id)
    service.start_packing(task.id, user=staff)
    service.complete_packing(task.id, pack(products), user=staff)
    return order


def test_shipping_a_packed_order(
    db_session: Session, shipments: ShipmentService, products, staff, carrier
):
    order = packed_order(db_session, products, staff)

    shipment = shipments.create(order.id, ShipmentCreate(carrier_id=carrier.id), user=staff)

    today = datetime.now(UTC).date()
    assert shipment.tracking_number == f"DHL{datetime.now(UTC):%y%m%d}{order.id:06d}"
    assert shipment.tracking_url == f"https://track.example.com/{shipment.tracking_number}"
    assert shipment.expected_delivery_date == add_working_days(today, 2)
    assert (shipment.package_count, shipment.weight_kg) == (2, Decimal("7.250"))
    assert shipment.status == ShipmentStatus.DISPATCHED
    [event] = shipment.events
    assert (event.event_type, event.description) == ("dispatched", "Handed to DHL Parcel")
    assert [i.quantity_shipped for i in order.items] == [2, 3]
    assert order.status == S.SHIPPED
    assert order.shipped_at is not None
    assert order.history[-1].note.startswith(f"DHL {shipment.tracking_number}, expected ")
    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "shipment.create"))
    assert audit.actor_id == staff.id and "2 parcel(s), 7.250 kg" in audit.summary


def test_only_packed_orders_can_be_shipped(
    db_session: Session, shipments: ShipmentService, products, staff, carrier
):
    order = picked_order(db_session, products, staff)

    with pytest.raises(ConflictError, match="is picked; only packed orders can be shipped"):
        shipments.create(order.id, ShipmentCreate(carrier_id=carrier.id), user=staff)


def test_given_tracking_number_and_date_and_their_rules(
    db_session: Session, shipments: ShipmentService, products, staff, carrier
):
    order = packed_order(db_session, products, staff)
    inactive = create_carrier(db_session, "OLD", is_active=False)
    later = date.today() + timedelta(days=10)

    with pytest.raises(UnprocessableError, match="Carrier not found"):
        shipments.create(order.id, ShipmentCreate(carrier_id=999), user=staff)
    with pytest.raises(UnprocessableError, match="OLD is not active"):
        shipments.create(order.id, ShipmentCreate(carrier_id=inactive.id), user=staff)
    with pytest.raises(UnprocessableError, match="cannot be in the past"):
        shipments.create(
            order.id,
            ShipmentCreate(carrier_id=carrier.id, expected_delivery_date=date(2020, 1, 1)),
            user=staff,
        )

    shipment = shipments.create(
        order.id,
        ShipmentCreate(
            carrier_id=carrier.id, tracking_number="ab-1234", expected_delivery_date=later
        ),
        user=staff,
    )
    assert (shipment.tracking_number, shipment.expected_delivery_date) == ("AB-1234", later)
    with pytest.raises(ValidationError):
        ShipmentCreate(carrier_id=1, tracking_number="no spaces allowed")


def test_working_days_skip_weekends():
    friday = date(2026, 11, 6)
    assert add_working_days(friday, 1) == date(2026, 11, 9)  # Monday
    assert add_working_days(friday, 2) == date(2026, 11, 10)
    assert add_working_days(friday, 0) == friday


def test_completed_packing_is_required(
    db_session: Session, shipments: ShipmentService, products, staff, carrier
):
    order = packed_order(db_session, products, staff)
    task = db_session.scalar(select(PackingTask).where(PackingTask.order_id == order.id))
    task.status = P.IN_PROGRESS  # simulate inconsistent data
    task.package_count = None
    db_session.commit()

    with pytest.raises(ConflictError, match="no completed packing"):
        shipments.create(order.id, ShipmentCreate(carrier_id=carrier.id), user=staff)
