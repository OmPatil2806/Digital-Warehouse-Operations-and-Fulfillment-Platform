"""Tests for the order service: creation, confirm, hold, cancel and the state machine."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import UnprocessableError
from app.models.audit import AuditLog
from app.models.catalog import Product
from app.models.inventory import ReferenceType, ReservationStatus
from app.models.order import Customer, Order, OrderStatus
from app.models.user import RoleName, User
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import ReceiveRequest, ReserveRequest
from app.schemas.order import OrderCreate
from app.services.inventory_service import InventoryService
from app.services.order_service import (
    TRANSITIONS,
    InvalidTransitionError,
    OrderService,
    can_transition,
    statuses_reachable_from,
)
from tests.factories import (
    create_bin,
    create_category,
    create_customer,
    create_product,
    create_user,
)

S = OrderStatus
YEAR = datetime.now(UTC).year


@pytest.fixture()
def customer(db_session: Session) -> Customer:
    return create_customer(
        db_session,
        name="Acme GmbH",
        address_line="Königstraße 1",
        postal_code="70173",
        city="Stuttgart",
        country="Germany",
    )


@pytest.fixture()
def products(db_session: Session) -> list[Product]:
    category = create_category(db_session)
    return [
        create_product(db_session, category, sku="LAP-001", unit_price=Decimal("899.00")),
        create_product(db_session, category, sku="MOU-001", unit_price=Decimal("24.90")),
    ]


@pytest.fixture()
def manager(db_session: Session) -> User:
    return create_user(db_session, "manager@example.com", roles=(RoleName.MANAGER,))


@pytest.fixture()
def service(db_session: Session) -> OrderService:
    return OrderService(db_session)


def new_order(customer: Customer, products: list[Product], **extra: object) -> OrderCreate:
    return OrderCreate(
        customer_id=customer.id,
        items=[
            {"product_id": products[0].id, "quantity": 2},
            {"product_id": products[1].id, "quantity": 3},
        ],
        **extra,
    )


def history(order: Order) -> list[tuple[str | None, str]]:
    return [(h.from_status, h.to_status) for h in order.history]


# --------------------------------------------------------------------------- create
def test_create_copies_prices_and_address_and_numbers_orders(
    db_session: Session, service: OrderService, customer, products, manager
):
    order = service.create(new_order(customer, products), user=manager)

    assert order.order_number == f"SO-{YEAR}-000001"
    assert order.status == S.CREATED
    assert order.subtotal == Decimal("1872.70")
    assert [(i.line_number, i.quantity, i.unit_price) for i in order.items] == [
        (1, 2, Decimal("899.00")),
        (2, 3, Decimal("24.90")),
    ]
    assert (order.ship_to_name, order.ship_to_address, order.ship_to_city) == (
        "Acme GmbH",
        "Königstraße 1",
        "Stuttgart",
    )
    assert order.created_by_id == manager.id
    assert history(order) == [(None, "created")]
    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "order.create"))
    assert audit.summary == f"Order SO-{YEAR}-000001 for CUST-0001: 2 line(s), 1872.70 EUR"
    assert audit.actor_id == manager.id

    # Later price changes do not change existing orders
    products[0].unit_price = Decimal("999.00")
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(Order, order.id).items[0].unit_price == Decimal("899.00")

    second = service.create(new_order(customer, products), user=None)
    assert second.order_number == f"SO-{YEAR}-000002"


def test_shipping_address_can_be_overridden(service: OrderService, customer, products):
    order = service.create(
        new_order(customer, products, ship_to_name="Acme Lager", ship_to_city="Esslingen"),
        user=None,
    )

    assert (order.ship_to_name, order.ship_to_city) == ("Acme Lager", "Esslingen")
    assert order.ship_to_country == "Germany"  # not overridden: from the customer


def test_create_refuses_unknown_or_archived_customers_and_products(
    db_session: Session, service: OrderService, customer, products
):
    with pytest.raises(UnprocessableError, match="Customer not found"):
        service.create(
            new_order(customer, products).model_copy(update={"customer_id": 999}), user=None
        )

    data = OrderCreate(customer_id=customer.id, items=[{"product_id": 999, "quantity": 1}])
    with pytest.raises(UnprocessableError, match="Product\\(s\\) not found: 999"):
        service.create(data, user=None)

    products[1].is_active = False
    db_session.commit()
    with pytest.raises(UnprocessableError, match="Archived products cannot be ordered: MOU-001"):
        service.create(new_order(customer, products), user=None)

    customer.is_active = False
    db_session.commit()
    with pytest.raises(UnprocessableError, match="CUST-0001 is archived"):
        service.create(new_order(customer, products), user=None)
    assert db_session.scalars(select(Order)).all() == []


@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {"items": [{"product_id": 1, "quantity": 0}]},
        {"items": [{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 2}]},
        {
            "items": [{"product_id": 1, "quantity": 1}],
            "requested_delivery_date": (date.today() - timedelta(days=2)).isoformat(),
        },
        {"items": [{"product_id": 1, "quantity": 1}], "priority": "asap"},
    ],
)
def test_invalid_order_requests(payload: dict):
    with pytest.raises(ValidationError):
        OrderCreate(customer_id=1, **payload)


# --------------------------------------------------------------- confirm and hold
def test_confirm_records_history_and_the_milestone(
    service: OrderService, customer, products, manager
):
    order = service.create(new_order(customer, products), user=None)

    service.confirm(order.id, user=manager, note="Checked by phone")

    assert order.status == S.CONFIRMED
    assert order.confirmed_at is not None
    last = order.history[-1]
    assert (last.from_status, last.to_status, last.changed_by_id, last.note) == (
        "created",
        "confirmed",
        manager.id,
        "Checked by phone",
    )
    with pytest.raises(InvalidTransitionError, match="is confirmed and cannot become confirmed"):
        service.confirm(order.id, user=manager)


def test_hold_and_release_return_to_the_previous_status(
    service: OrderService, customer, products, manager
):
    order = service.create(new_order(customer, products), user=None)
    service.confirm(order.id, user=None)

    service.hold(order.id, user=manager, reason="Payment not received")
    assert (order.status, order.status_before_hold) == (S.ON_HOLD, S.CONFIRMED)
    with pytest.raises(InvalidTransitionError, match="is on hold; release the hold first"):
        service.confirm(order.id, user=manager)  # confirming again is not "releasing"

    service.release_hold(order.id, user=manager, note="Paid")
    assert (order.status, order.status_before_hold) == (S.CONFIRMED, None)
    assert history(order)[-2:] == [("confirmed", "on_hold"), ("on_hold", "confirmed")]
    with pytest.raises(InvalidTransitionError, match="is not on hold"):
        service.release_hold(order.id, user=manager)


def test_released_order_cannot_jump_to_another_status(service: OrderService, customer, products):
    order = service.create(new_order(customer, products), user=None)
    service.hold(order.id, user=None, reason="Check credit")

    with pytest.raises(InvalidTransitionError, match="release the hold first"):
        service.transition(order, S.ALLOCATED, user=None)
    with pytest.raises(InvalidTransitionError, match="goes back to created when released"):
        service.transition(order, S.ALLOCATED, user=None, releasing_hold=True)
    service.cancel(order.id, user=None, reason="Credit refused")  # cancelling is allowed
    assert order.status == S.CANCELLED


# --------------------------------------------------------------------------- cancel
def test_cancel_releases_the_orders_reservations(
    db_session: Session, service: OrderService, customer, products, manager
):
    bin_ = create_bin(db_session)
    inventory = InventoryService(db_session)
    inventory.receive(
        ReceiveRequest(product_id=products[0].id, bin_id=bin_.id, quantity=10), user=None
    )
    order = service.create(new_order(customer, products), user=None)
    inventory.reserve(
        ReserveRequest(
            product_id=products[0].id,
            quantity=2,
            reference_type=ReferenceType.ORDER,
            reference_id=order.id,
        ),
        user=None,
    )

    service.cancel(order.id, user=manager, reason="Customer changed their mind")

    db_session.expire_all()
    order = db_session.get(Order, order.id)
    assert (order.status, order.cancel_reason) == (S.CANCELLED, "Customer changed their mind")
    assert order.cancelled_at is not None
    row = InventoryRepository(db_session).get_row(products[0].id, bin_.id)
    assert (row.quantity_on_hand, row.quantity_reserved) == (10, 0)
    [reservation] = InventoryRepository(db_session).search_reservations(offset=0, limit=5)[0]
    assert reservation.status == ReservationStatus.RELEASED
    with pytest.raises(InvalidTransitionError, match="is cancelled and cannot become"):
        service.confirm(order.id, user=manager)


def test_orders_cannot_be_cancelled_once_picking_started(service: OrderService, customer, products):
    order = service.create(new_order(customer, products), user=None)
    for status in (S.CONFIRMED, S.INVENTORY_RESERVED, S.ALLOCATED, S.PICKING):
        service.transition(order, status, user=None)

    with pytest.raises(InvalidTransitionError, match="is picking and cannot become cancelled"):
        service.cancel(order.id, user=None, reason="Too late")
    with pytest.raises(InvalidTransitionError):
        service.hold(order.id, user=None, reason="Too late")


# -------------------------------------------------------------------- state machine
def test_every_status_has_rules():
    assert set(TRANSITIONS) == set(OrderStatus)
    for targets in TRANSITIONS.values():
        assert targets <= set(OrderStatus)


def test_the_main_flow_is_allowed_end_to_end(service: OrderService, customer, products):
    order = service.create(new_order(customer, products), user=None)
    flow = [
        S.CONFIRMED,
        S.INVENTORY_RESERVED,
        S.ALLOCATED,
        S.PICKING,
        S.PICKED,
        S.PACKING,
        S.PACKED,
        S.SHIPPED,
        S.DELAYED,
        S.DELIVERED,
        S.RETURNED,
    ]
    for status in flow:
        service.transition(order, status, user=None)

    assert [to for _, to in history(order)] == ["created", *flow]
    assert order.shipped_at is not None and order.delivered_at is not None


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.CREATED, S.SHIPPED),
        (S.CREATED, S.INVENTORY_RESERVED),  # must be confirmed first
        (S.CONFIRMED, S.PICKING),
        (S.PICKED, S.CANCELLED),
        (S.SHIPPED, S.CANCELLED),
        (S.PACKED, S.DELIVERED),
        (S.DELIVERED, S.PICKING),
        (S.CANCELLED, S.CONFIRMED),
        (S.RETURNED, S.DELIVERED),
        (S.BACKORDERED, S.ALLOCATED),  # stock must be reserved first
    ],
)
def test_invalid_transitions_are_rejected(
    db_session: Session, service: OrderService, customer, products, current, target
):
    order = service.create(new_order(customer, products), user=None)
    order.status = current
    db_session.commit()
    entries = len(order.history)

    assert can_transition(current, target) is False
    with pytest.raises(InvalidTransitionError):
        service.transition(order, target, user=None)
    assert order.status == current
    assert len(order.history) == entries


def test_reachable_statuses_for_the_ui():
    assert statuses_reachable_from(S.CREATED) == [S.CONFIRMED, S.ON_HOLD, S.CANCELLED]
    assert statuses_reachable_from(S.SHIPPED) == [S.DELIVERED, S.DELAYED]
    assert statuses_reachable_from(S.CANCELLED) == []
