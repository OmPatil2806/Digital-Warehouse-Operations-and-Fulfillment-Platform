"""Tests for picking: route, scans, stock effects, short picks and cancellation."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, UnprocessableError
from app.models.catalog import Product
from app.models.fulfillment import PickingTask, PickingTaskStatus
from app.models.inventory import CycleCount, InventoryMovement, ReservationStatus
from app.models.order import Customer, Order, OrderStatus
from app.models.user import RoleName, User
from app.models.warehouse import Bin
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.fulfillment import PickConfirmation
from app.schemas.inventory import ReceiveRequest
from app.schemas.order import OrderCreate
from app.services.fulfillment_service import FulfillmentService
from app.services.inventory_service import InventoryService
from app.services.order_service import InvalidTransitionError, OrderService
from tests.factories import (
    create_bin,
    create_category,
    create_customer,
    create_product,
    create_user,
)

S = OrderStatus
T = PickingTaskStatus


@pytest.fixture()
def customer(db_session: Session) -> Customer:
    return create_customer(db_session)


@pytest.fixture()
def products(db_session: Session) -> list[Product]:
    category = create_category(db_session)
    return [
        create_product(db_session, category, sku="LAP-001", barcode="4006381333931"),
        create_product(db_session, category, sku="MOU-001", unit_price=Decimal("24.90")),
    ]


@pytest.fixture()
def bins(db_session: Session) -> dict[str, Bin]:
    near = create_bin(db_session, "WH01-ZA-R01-S01-B01")
    far_low = create_bin(db_session, "WH01-ZA-R09-S01-B01")
    far_high = create_bin(db_session, "WH01-ZA-R09-S02-B01")
    spare = create_bin(db_session, "WH01-ZA-R05-S01-B01")
    near.shelf.rack.distance_to_packing_m = Decimal("5.0")
    far_low.shelf.rack.distance_to_packing_m = Decimal("40.0")
    spare.shelf.rack.distance_to_packing_m = Decimal("20.0")
    db_session.commit()
    return {"near": near, "far_low": far_low, "far_high": far_high, "spare": spare}


@pytest.fixture()
def picker(db_session: Session) -> User:
    return create_user(
        db_session, "sam@example.com", full_name="Sam Staff", roles=(RoleName.STAFF,)
    )


@pytest.fixture()
def service(db_session: Session) -> FulfillmentService:
    return FulfillmentService(db_session)


def receive(db: Session, product: Product, bin_: Bin, quantity: int) -> None:
    InventoryService(db).receive(
        ReceiveRequest(product_id=product.id, bin_id=bin_.id, quantity=quantity), user=None
    )


def reserved_order(db: Session, customer: Customer, lines: list[tuple[Product, int]]) -> Order:
    orders = OrderService(db)
    order = orders.create(
        OrderCreate(
            customer_id=customer.id,
            items=[{"product_id": p.id, "quantity": q} for p, q in lines],
        ),
        user=None,
    )
    return orders.confirm(order.id, user=None)


def scan(task: PickingTask, quantity: int | None = None, **overrides: object) -> PickConfirmation:
    values: dict[str, object] = {
        "bin_code": task.bin.location_code,
        "product_code": task.product.sku,
        "quantity_picked": task.quantity if quantity is None else quantity,
    }
    values.update(overrides)
    return PickConfirmation(**values)


def stock(db: Session, product: Product, bin_: Bin) -> tuple[int, int]:
    row = InventoryRepository(db).get_row(product.id, bin_.id)
    db.refresh(row)
    return row.quantity_on_hand, row.quantity_reserved


@pytest.fixture()
def stocked(db_session: Session, products, bins) -> None:
    """LAP: 1 near, 2 far (low shelf), 2 far (high shelf); MOU: 3 near."""
    receive(db_session, products[0], bins["near"], 1)
    receive(db_session, products[0], bins["far_low"], 2)
    receive(db_session, products[0], bins["far_high"], 2)
    receive(db_session, products[1], bins["near"], 3)


# -------------------------------------------------------------------------- allocate
def test_allocate_creates_one_route_farthest_first(
    db_session: Session, service: FulfillmentService, customer, products, bins, stocked
):
    order = reserved_order(db_session, customer, [(products[0], 5), (products[1], 2)])
    assert order.status == S.INVENTORY_RESERVED

    tasks = service.allocate(order.id, user=None)

    route = [(t.sequence, t.bin.location_code, t.product.sku, t.quantity) for t in tasks]
    assert route == [
        (1, "WH01-ZA-R09-S01-B01", "LAP-001", 2),  # farthest rack, low shelf first
        (2, "WH01-ZA-R09-S02-B01", "LAP-001", 2),
        (3, "WH01-ZA-R01-S01-B01", "LAP-001", 1),  # near packing: last
        (4, "WH01-ZA-R01-S01-B01", "MOU-001", 2),
    ]
    assert {t.status for t in tasks} == {T.PENDING}
    assert order.status == S.ALLOCATED
    assert order.history[-1].note == "4 picking task(s) created"


def test_only_fully_reserved_orders_can_be_allocated(
    db_session: Session, service: FulfillmentService, customer, products, bins, stocked
):
    order = reserved_order(db_session, customer, [(products[0], 9)])  # only 5 in stock
    assert order.status == S.PARTIALLY_ALLOCATED

    with pytest.raises(InvalidTransitionError, match="cannot become allocated"):
        service.allocate(order.id, user=None)
    assert db_session.scalar(select(func.count()).select_from(PickingTask)) == 0


# ------------------------------------------------------------------------- picking
def test_picking_reduces_stock_correctly(
    db_session: Session, service: FulfillmentService, customer, products, bins, stocked, picker
):
    order = reserved_order(db_session, customer, [(products[0], 5), (products[1], 2)])
    tasks = service.allocate(order.id, user=None)

    service.start(tasks[0].id, user=picker)
    assert (tasks[0].status, tasks[0].assigned_to_id) == (T.IN_PROGRESS, picker.id)
    assert order.status == S.PICKING
    assert order.history[-1].note == "Picked by Sam Staff"

    for task in tasks:
        if task.status == T.PENDING:
            service.start(task.id, user=picker)
        service.complete(task.id, scan(task), user=picker)

    assert [stock(db_session, products[0], bins[b]) for b in ("far_low", "far_high", "near")] == [
        (0, 0),
        (0, 0),
        (0, 0),
    ]
    assert stock(db_session, products[1], bins["near"]) == (1, 0)  # 3 - 2 picked
    picks = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.movement_type == "pick")
    ).all()
    # LAP 2 + 2 + 1 and MOU 2: on hand and reserved both go down by the picked units
    assert sorted((m.on_hand_delta, m.reserved_delta) for m in picks) == [
        (-2, -2),
        (-2, -2),
        (-2, -2),
        (-1, -1),
    ]
    assert {(m.reference_type, m.reference_id) for m in picks} == {("order", order.id)}
    assert {t.reservation.status for t in tasks} == {ReservationStatus.FULFILLED}
    assert [(i.quantity_picked, i.quantity_reserved) for i in order.items] == [(5, 0), (2, 0)]
    assert order.status == S.PICKED
    assert order.history[-1].note == "All units picked"


def test_scans_must_match_the_task(
    db_session: Session, service: FulfillmentService, customer, products, bins, stocked, picker
):
    order = reserved_order(db_session, customer, [(products[0], 1)])
    [task] = service.allocate(order.id, user=None)

    with pytest.raises(ConflictError, match="start it before confirming"):
        service.complete(task.id, scan(task), user=picker)
    service.start(task.id, user=picker)
    with pytest.raises(ConflictError, match="already in progress"):
        service.start(task.id, user=picker)

    with pytest.raises(UnprocessableError, match="Wrong bin: scanned WH01-ZA-R09-S01-B01"):
        service.complete(task.id, scan(task, bin_code="wh01-za-r09-s01-b01"), user=picker)
    with pytest.raises(UnprocessableError, match="Wrong product: scanned MOU-001"):
        service.complete(task.id, scan(task, product_code="MOU-001"), user=picker)
    assert stock(db_session, products[0], bins["near"]) == (1, 1)  # nothing changed

    # The barcode works as well as the SKU; codes are not case-sensitive
    service.complete(
        task.id,
        scan(task, bin_code=" wh01-za-r01-s01-b01 ", product_code="4006381333931"),
        user=picker,
    )
    assert task.status == T.COMPLETED


def test_short_pick_is_written_off_counted_and_replaced(
    db_session: Session, service: FulfillmentService, customer, products, bins, stocked, picker
):
    receive(db_session, products[1], bins["spare"], 5)
    order = reserved_order(db_session, customer, [(products[1], 3)])  # all 3 in the near bin
    [task] = service.allocate(order.id, user=None)
    service.start(task.id, user=picker)

    with pytest.raises(UnprocessableError, match="say why units are missing"):
        service.complete(task.id, scan(task, 1), user=picker)
    service.complete(task.id, scan(task, 1, short_reason="Only one in the bin"), user=picker)

    assert (task.status, task.quantity_picked) == (T.SHORT, 1)
    # The 2 missing units are written off: the near bin is now empty
    assert stock(db_session, products[1], bins["near"]) == (0, 0)
    count = db_session.scalars(select(CycleCount).where(CycleCount.bin_id == bins["near"].id)).one()
    assert count.status == "open" and "Only one in the bin" in count.note
    # ...and replaced from the spare bin as a new task at the end of the route
    replacement = service.tasks_for_order(order.id)[-1]
    assert (replacement.sequence, replacement.bin_id, replacement.quantity) == (
        2,
        bins["spare"].id,
        2,
    )
    assert order.status == S.PICKING  # still a task to do
    service.start(replacement.id, user=picker)
    service.complete(replacement.id, scan(replacement), user=picker)
    assert order.status == S.PICKED
    assert order.history[-1].note == "All units picked"
    assert order.items[0].quantity_picked == 3


def test_short_pick_without_other_stock_ships_short(
    db_session: Session, service: FulfillmentService, customer, products, bins, stocked, picker
):
    order = reserved_order(db_session, customer, [(products[1], 3)])
    [task] = service.allocate(order.id, user=None)
    service.start(task.id, user=picker)

    service.complete(task.id, scan(task, 1, short_reason="Two missing"), user=picker)

    assert order.status == S.PICKED
    assert order.history[-1].note == "Picked with 2 unit(s) short"
    assert (order.items[0].quantity_picked, order.items[0].quantity_reserved) == (1, 0)


def test_tasks_cannot_be_started_while_the_order_is_on_hold(
    db_session: Session, service: FulfillmentService, customer, products, bins, stocked, picker
):
    order = reserved_order(db_session, customer, [(products[0], 1)])
    [task] = service.allocate(order.id, user=None)
    OrderService(db_session).hold(order.id, user=None, reason="Address check")

    with pytest.raises(ConflictError, match="is on hold; it cannot be picked now"):
        service.start(task.id, user=picker)


def test_cancelling_an_allocated_order_cancels_its_tasks(
    db_session: Session, service: FulfillmentService, customer, products, bins, stocked
):
    order = reserved_order(db_session, customer, [(products[0], 5)])
    tasks = service.allocate(order.id, user=None)

    OrderService(db_session).cancel(order.id, user=None, reason="Customer cancelled")

    db_session.expire_all()
    assert {db_session.get(PickingTask, t.id).status for t in tasks} == {T.CANCELLED}
    assert stock(db_session, products[0], bins["far_low"]) == (2, 0)


def test_movements_still_explain_all_stock_after_picking(
    db_session: Session, service: FulfillmentService, customer, products, bins, stocked, picker
):
    receive(db_session, products[1], bins["spare"], 5)
    order = reserved_order(db_session, customer, [(products[0], 4), (products[1], 4)])
    for task in service.allocate(order.id, user=None):
        service.start(task.id, user=picker)
        short = task.quantity > 1 and task.product_id == products[1].id
        picked = task.quantity - 1 if short else task.quantity
        service.complete(
            task.id, scan(task, picked, short_reason="One missing" if short else None), user=picker
        )
    for task in service.tasks_for_order(order.id):
        if task.status == T.PENDING:
            service.start(task.id, user=picker)
            service.complete(task.id, scan(task), user=picker)

    for product in products:
        for bin_ in bins.values():
            row = InventoryRepository(db_session).get_row(product.id, bin_.id)
            if row is None:
                continue
            on_hand, reserved = db_session.execute(
                select(
                    func.sum(InventoryMovement.on_hand_delta),
                    func.sum(InventoryMovement.reserved_delta),
                ).where(
                    InventoryMovement.product_id == product.id,
                    InventoryMovement.bin_id == bin_.id,
                )
            ).one()
            assert (on_hand, reserved) == stock(db_session, product, bin_)
    assert order.status == S.PICKED
