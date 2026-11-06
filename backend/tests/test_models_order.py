"""Tests for the customer and order tables."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.order import (
    Customer,
    CustomerType,
    Order,
    OrderItem,
    OrderPriority,
    OrderStatus,
    OrderStatusHistory,
)
from app.models.user import RoleName
from tests.factories import create_category, create_customer, create_product, create_user


@pytest.fixture()
def customer(db_session: Session) -> Customer:
    return create_customer(db_session, city="Stuttgart", country="Germany")


@pytest.fixture()
def products(db_session: Session) -> list[Product]:
    category = create_category(db_session)
    return [
        create_product(db_session, category, sku="LAP-001", unit_price=Decimal("899.00")),
        create_product(db_session, category, sku="MOU-001", unit_price=Decimal("24.90")),
    ]


def make_order(customer: Customer, number: str = "SO-2026-000001", **overrides: object) -> Order:
    values: dict[str, object] = {
        "order_number": number,
        "customer_id": customer.id,
        "ship_to_name": customer.name,
        "ship_to_city": customer.city,
    }
    values.update(overrides)
    return Order(**values)


def line(product: Product, number: int = 1, quantity: int = 2, **overrides: object) -> OrderItem:
    values: dict[str, object] = {
        "line_number": number,
        "product_id": product.id,
        "quantity": quantity,
        "unit_price": product.unit_price,
    }
    values.update(overrides)
    return OrderItem(**values)


def save(db: Session, obj: object) -> object:
    db.add(obj)
    db.commit()
    return obj


def expect_integrity_error(db: Session, obj: object, match: str | None = None) -> None:
    db.add(obj)
    with pytest.raises(IntegrityError, match=match):
        db.commit()
    db.rollback()


# ------------------------------------------------------------------------ customers
def test_customer_defaults_and_login_link(db_session: Session, customer: Customer):
    assert customer.customer_type == CustomerType.BUSINESS
    assert customer.is_active is True
    assert customer.user is None

    login = create_user(db_session, "chris@example.com", roles=(RoleName.CUSTOMER,))
    customer.user_id = login.id
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(Customer, customer.id).user.email == "chris@example.com"

    # One customer per login, and codes are unique
    expect_integrity_error(db_session, Customer(code="CUST-0002", name="Other", user_id=login.id))
    expect_integrity_error(db_session, Customer(code="CUST-0001", name="Copy"))
    expect_integrity_error(
        db_session, Customer(code="CUST-0003", name="X", customer_type="robot"), "valid_type"
    )


# --------------------------------------------------------------------------- orders
def test_order_with_lines_round_trip(db_session: Session, customer: Customer, products):
    order = make_order(customer, requested_delivery_date=date(2026, 11, 20))
    order.items = [line(products[0], 1, 2), line(products[1], 2, 3)]
    order.subtotal = sum((item.line_total for item in order.items), Decimal("0"))
    save(db_session, order)
    db_session.expire_all()

    order = db_session.get(Order, order.id)
    assert order.status == OrderStatus.CREATED
    assert order.priority == OrderPriority.NORMAL
    assert order.subtotal == Decimal("1872.70")  # 2 x 899.00 + 3 x 24.90
    assert order.requested_delivery_date == date(2026, 11, 20)
    assert [item.product.sku for item in order.items] == ["LAP-001", "MOU-001"]
    assert order.total_quantity == 5
    assert order.items[1].line_total == Decimal("74.70")
    assert order.items[0].quantity_missing == 2  # nothing reserved yet
    assert order.customer.orders == [order]


def test_order_numbers_are_unique_and_values_valid(db_session: Session, customer: Customer):
    save(db_session, make_order(customer))

    expect_integrity_error(db_session, make_order(customer), "UNIQUE")
    expect_integrity_error(
        db_session, make_order(customer, "SO-2", status="teleported"), "valid_status"
    )
    expect_integrity_error(
        db_session, make_order(customer, "SO-3", priority="asap"), "valid_priority"
    )


def test_one_line_per_product_and_per_line_number(
    db_session: Session, customer: Customer, products
):
    order = save(db_session, make_order(customer))

    save(db_session, OrderItem(order_id=order.id, **_line_values(products[0], 1)))
    expect_integrity_error(
        db_session, OrderItem(order_id=order.id, **_line_values(products[0], 2)), "UNIQUE"
    )
    expect_integrity_error(
        db_session, OrderItem(order_id=order.id, **_line_values(products[1], 1)), "UNIQUE"
    )


def _line_values(product: Product, number: int) -> dict[str, object]:
    return {
        "line_number": number,
        "product_id": product.id,
        "quantity": 1,
        "unit_price": product.unit_price,
    }


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"quantity": 0}, "quantity_positive"),
        ({"unit_price": Decimal("-1")}, "price_not_negative"),
        ({"quantity_reserved": 3}, "reserved_in_range"),  # more than ordered (2)
        ({"quantity_picked": 3}, "picked_in_range"),
        ({"quantity_picked": 1, "quantity_packed": 2}, "packed_le_picked"),
        (
            {"quantity_picked": 2, "quantity_packed": 1, "quantity_shipped": 2},
            "shipped_le_packed",
        ),
        (
            {
                "quantity_picked": 2,
                "quantity_packed": 2,
                "quantity_shipped": 1,
                "quantity_returned": 2,
            },
            "returned_le_shipped",
        ),
        ({"line_number": 0}, "line_number_positive"),
    ],
)
def test_line_quantities_only_flow_forward(
    db_session: Session, customer: Customer, products, overrides: dict, constraint: str
):
    order = save(db_session, make_order(customer))

    expect_integrity_error(
        db_session,
        OrderItem(
            order_id=order.id, **{**_line_values(products[0], 1), "quantity": 2, **overrides}
        ),
        constraint,
    )


def test_a_fully_processed_line_is_valid(db_session: Session, customer: Customer, products):
    order = make_order(customer, status=OrderStatus.DELIVERED)
    order.items = [
        line(
            products[0],
            quantity=3,
            quantity_picked=3,
            quantity_packed=3,
            quantity_shipped=3,
            quantity_returned=1,
        )
    ]
    save(db_session, order)


def test_products_and_customers_with_orders_cannot_be_deleted(
    db_session: Session, customer: Customer, products
):
    order = make_order(customer)
    order.items = [line(products[0])]
    save(db_session, order)

    for statement in (
        delete(Product).filter_by(id=products[0].id),
        delete(Customer).filter_by(id=customer.id),
    ):
        with pytest.raises(IntegrityError):
            db_session.execute(statement)
        db_session.rollback()


# -------------------------------------------------------------------------- history
def test_status_history_is_ordered_and_deleted_with_the_order(
    db_session: Session, customer: Customer, products
):
    manager = create_user(db_session, "manager@example.com", roles=(RoleName.MANAGER,))
    order = make_order(customer)
    order.items = [line(products[0])]
    order.history = [
        OrderStatusHistory(to_status=OrderStatus.CREATED),
        OrderStatusHistory(
            from_status=OrderStatus.CREATED,
            to_status=OrderStatus.CONFIRMED,
            changed_by_id=manager.id,
            note="Checked by phone",
        ),
    ]
    save(db_session, order)
    db_session.expire_all()

    history = db_session.get(Order, order.id).history
    assert [(h.from_status, h.to_status) for h in history] == [
        (None, "created"),
        ("created", "confirmed"),
    ]
    assert history[1].changed_by.email == "manager@example.com"
    assert history[0].created_at.tzinfo is not None

    db_session.execute(delete(Order).filter_by(id=order.id))
    assert db_session.scalars(select(OrderStatusHistory)).all() == []
    assert db_session.scalars(select(OrderItem)).all() == []


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"from_status": "created", "to_status": "created"}, "is_a_change"),
        ({"to_status": "lost"}, "valid_to"),
        ({"from_status": "nowhere", "to_status": "created"}, "valid_from"),
    ],
)
def test_invalid_history_entries(
    db_session: Session, customer: Customer, values: dict, constraint: str
):
    order = save(db_session, make_order(customer))

    expect_integrity_error(db_session, OrderStatusHistory(order_id=order.id, **values), constraint)
