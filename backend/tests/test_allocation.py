"""Tests for reserving stock for orders and filling backorders automatically."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.inventory import ReservationStatus, StockReservation
from app.models.order import Customer, Order, OrderPriority, OrderStatus
from app.models.warehouse import Bin
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import ReceiveRequest
from app.schemas.order import OrderCreate
from app.services.inventory_service import InventoryService
from app.services.order_service import InvalidTransitionError, OrderService
from tests.factories import create_bin, create_category, create_customer, create_product

S = OrderStatus


@pytest.fixture()
def customer(db_session: Session) -> Customer:
    return create_customer(db_session)


@pytest.fixture()
def products(db_session: Session) -> list[Product]:
    category = create_category(db_session)
    return [
        create_product(db_session, category, sku="LAP-001", unit_price=Decimal("899.00")),
        create_product(db_session, category, sku="MOU-001", unit_price=Decimal("24.90")),
    ]


@pytest.fixture()
def bins(db_session: Session) -> dict[str, Bin]:
    return {
        "a": create_bin(db_session, "WH01-ZA-R01-S01-B01"),
        "b": create_bin(db_session, "WH01-ZA-R01-S01-B02"),
        "far": create_bin(db_session, "WH02-ZA-R01-S01-B01"),
    }


@pytest.fixture()
def orders(db_session: Session) -> OrderService:
    return OrderService(db_session)


def receive(db: Session, product: Product, bin_: Bin, quantity: int) -> None:
    InventoryService(db).receive(
        ReceiveRequest(product_id=product.id, bin_id=bin_.id, quantity=quantity), user=None
    )


def place(
    orders: OrderService,
    customer: Customer,
    lines: list[tuple[Product, int]],
    priority: OrderPriority = OrderPriority.NORMAL,
) -> Order:
    order = orders.create(
        OrderCreate(
            customer_id=customer.id,
            items=[{"product_id": p.id, "quantity": q} for p, q in lines],
            priority=priority,
        ),
        user=None,
    )
    return orders.confirm(order.id, user=None)


def reserved_for(db: Session, order: Order) -> list[tuple[int, int, int]]:
    """(product_id, bin_id, quantity) of the order's active reservations."""
    return sorted(
        (r.product_id, r.bin_id, r.quantity)
        for r in db.scalars(
            select(StockReservation).where(
                StockReservation.reference_type == "order",
                StockReservation.reference_id == order.id,
                StockReservation.status == ReservationStatus.ACTIVE.value,
            )
        )
    )


def stock(db: Session, product: Product, bin_: Bin) -> tuple[int, int]:
    row = InventoryRepository(db).get_row(product.id, bin_.id)
    db.refresh(row)
    return row.quantity_on_hand, row.quantity_reserved


def test_confirming_reserves_everything_when_stock_is_there(
    db_session: Session, orders: OrderService, customer, products, bins
):
    receive(db_session, products[0], bins["a"], 1)
    receive(db_session, products[0], bins["b"], 5)
    receive(db_session, products[1], bins["b"], 10)

    order = place(orders, customer, [(products[0], 3), (products[1], 4)])

    assert order.status == S.INVENTORY_RESERVED
    assert [i.quantity_reserved for i in order.items] == [3, 4]
    assert reserved_for(db_session, order) == [
        (products[0].id, bins["a"].id, 1),  # split over the best bins
        (products[0].id, bins["b"].id, 2),
        (products[1].id, bins["b"].id, 4),
    ]
    assert stock(db_session, products[0], bins["b"]) == (5, 2)  # on hand unchanged
    assert order.warehouse.code == "WH01"
    assert [(h.from_status, h.to_status, h.note) for h in order.history[-2:]] == [
        ("created", "confirmed", None),
        ("confirmed", "inventory_reserved", "7 of 7 units reserved"),
    ]


def test_not_enough_stock_gives_partially_allocated_or_backordered(
    db_session: Session, orders: OrderService, customer, products, bins
):
    receive(db_session, products[0], bins["a"], 2)

    partial = place(orders, customer, [(products[0], 3), (products[1], 1)])
    nothing = place(orders, customer, [(products[1], 2)])

    assert partial.status == S.PARTIALLY_ALLOCATED
    assert [(i.quantity_reserved, i.quantity_missing) for i in partial.items] == [(2, 1), (0, 1)]
    assert partial.history[-1].note == "2 of 4 units reserved"
    assert nothing.status == S.BACKORDERED
    assert nothing.warehouse_id is None  # no warehouse has any stock yet


def test_receiving_goods_fills_backorders_automatically(
    db_session: Session, orders: OrderService, customer, products, bins
):
    receive(db_session, products[0], bins["a"], 2)
    order = place(orders, customer, [(products[0], 3), (products[1], 1)])
    assert order.status == S.PARTIALLY_ALLOCATED

    receive(db_session, products[0], bins["b"], 1)  # LAP complete, MOU still missing
    db_session.refresh(order)
    assert order.status == S.PARTIALLY_ALLOCATED
    assert [i.quantity_missing for i in order.items] == [0, 1]

    receive(db_session, products[1], bins["b"], 5)
    db_session.refresh(order)
    assert order.status == S.INVENTORY_RESERVED
    assert order.history[-1].note == "4 of 4 units reserved"
    assert order.history[-1].changed_by_id is None  # done by the system


def test_urgent_orders_get_new_stock_first(
    db_session: Session, orders: OrderService, customer, products, bins
):
    older = place(orders, customer, [(products[0], 2)])
    urgent = place(orders, customer, [(products[0], 2)], priority=OrderPriority.URGENT)
    assert (older.status, urgent.status) == (S.BACKORDERED, S.BACKORDERED)

    receive(db_session, products[0], bins["a"], 3)

    db_session.refresh(older)
    db_session.refresh(urgent)
    assert urgent.status == S.INVENTORY_RESERVED
    assert older.status == S.PARTIALLY_ALLOCATED  # gets the one unit that is left
    assert stock(db_session, products[0], bins["a"]) == (3, 3)


def test_cancelling_an_order_frees_stock_for_waiting_orders(
    db_session: Session, orders: OrderService, customer, products, bins
):
    receive(db_session, products[0], bins["a"], 2)
    first = place(orders, customer, [(products[0], 2)])
    waiting = place(orders, customer, [(products[0], 2)])
    assert (first.status, waiting.status) == (S.INVENTORY_RESERVED, S.BACKORDERED)

    orders.cancel(first.id, user=None, reason="Customer cancelled")

    db_session.expire_all()
    assert db_session.get(Order, waiting.id).status == S.INVENTORY_RESERVED
    assert reserved_for(db_session, db_session.get(Order, first.id)) == []
    assert [i.quantity_reserved for i in db_session.get(Order, first.id).items] == [0]
    assert stock(db_session, products[0], bins["a"]) == (2, 2)


def test_an_order_is_served_from_one_warehouse(
    db_session: Session, orders: OrderService, customer, products, bins
):
    receive(db_session, products[0], bins["a"], 3)  # WH01
    receive(db_session, products[0], bins["far"], 5)  # WH02 can cover the whole line

    order = place(orders, customer, [(products[0], 5)])

    assert order.warehouse.code == "WH02"
    assert reserved_for(db_session, order) == [(products[0].id, bins["far"].id, 5)]

    # A later backorder stays with the order's warehouse
    second = place(orders, customer, [(products[0], 4)])
    assert second.warehouse.code == "WH01"
    assert second.status == S.PARTIALLY_ALLOCATED  # 3 in WH01; WH02 is not mixed in


def test_orders_on_hold_are_not_filled_automatically(
    db_session: Session, orders: OrderService, customer, products, bins
):
    order = place(orders, customer, [(products[0], 2)])
    orders.hold(order.id, user=None, reason="Credit check")

    receive(db_session, products[0], bins["a"], 5)

    db_session.refresh(order)
    assert order.status == S.ON_HOLD
    orders.release_hold(order.id, user=None)
    assert order.status == S.BACKORDERED
    orders.reserve_stock(order.id, user=None)  # retry by hand
    assert order.status == S.INVENTORY_RESERVED


def test_manual_retry_only_for_waiting_orders(
    db_session: Session, orders: OrderService, customer, products, bins
):
    receive(db_session, products[0], bins["a"], 5)
    order = place(orders, customer, [(products[0], 2)])

    with pytest.raises(InvalidTransitionError, match="only backordered or partially"):
        orders.reserve_stock(order.id, user=None)


def test_reservations_always_match_the_order_lines(
    db_session: Session, orders: OrderService, customer, products, bins
):
    """After many orders and receipts, each line's reserved quantity equals its active
    reservations, and the bins' reserved totals equal all active reservations."""
    placed = []
    for quantity in (3, 1, 4, 2, 5):
        placed.append(place(orders, customer, [(products[0], quantity), (products[1], 1)]))
    for bin_, quantity in ((bins["a"], 4), (bins["b"], 3), (bins["a"], 2), (bins["b"], 6)):
        receive(db_session, products[0], bin_, quantity)
        receive(db_session, products[1], bin_, 1)
    orders.cancel(placed[2].id, user=None, reason="Not needed")

    db_session.expire_all()
    for order in placed:
        order = db_session.get(Order, order.id)
        for item in order.items:
            held = sum(q for p, _, q in reserved_for(db_session, order) if p == item.product_id)
            assert held == item.quantity_reserved
    active_total = db_session.scalar(
        select(func.sum(StockReservation.quantity)).where(
            StockReservation.status == ReservationStatus.ACTIVE.value
        )
    )
    bin_total = sum(
        stock(db_session, p, b)[1]
        for p in products
        for b in (bins["a"], bins["b"])
        if InventoryRepository(db_session).get_row(p.id, b.id)
    )
    assert active_total == bin_total
    statuses = [db_session.get(Order, o.id).status for o in placed]
    assert statuses.count(S.CANCELLED) == 1


def test_reserving_does_nothing_for_orders_that_do_not_wait_for_stock(
    db_session: Session, orders: OrderService, customer, products, bins
):
    from app.services.allocation_service import AllocationService

    receive(db_session, products[0], bins["a"], 5)
    order = orders.create(
        OrderCreate(customer_id=customer.id, items=[{"product_id": products[0].id, "quantity": 2}]),
        user=None,
    )
    allocation = AllocationService(db_session)

    assert allocation.reserve_for_order(order, user=None) == S.CREATED  # not confirmed yet
    orders.hold(order.id, user=None, reason="Credit check")
    assert allocation.reserve_for_order(order, user=None) == S.ON_HOLD
    assert reserved_for(db_session, order) == []
