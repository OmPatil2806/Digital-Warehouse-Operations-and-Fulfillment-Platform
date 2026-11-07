"""Fulfillment KPIs on hand-built orders, shipments and picking tasks.

Period: 1-7 Nov 2026. Milestones per order (created / confirmed / shipped / delivered):

| Order | Created        | Confirmed   | Shipped        | Delivered   | Status now  |
|-------|----------------|-------------|----------------|-------------|-------------|
| 1     | 30 Oct 08:00   | 30 Oct 10:00| 1 Nov 10:00    | 3 Nov 10:00 | delivered   |
| 2     | 1 Nov 00:00    | 1 Nov 02:00 | 1 Nov 14:00    | 6 Nov 00:00 | delivered   |
| 3     | 2 Nov 09:00    | 2 Nov 10:00 | 8 Nov 00:00 *  | -           | shipped     |
| 4     | 3 Nov 10:00    | -           | cancelled 4 Nov| -           | cancelled   |
| 5     | 7 Nov 23:59:59 | -           | -              | -           | created     |
| 6     | 31 Oct 23:59:59| -           | -              | -           | backordered |
| 7     | 2 Nov 00:00    | (missing)   | 4 Nov 00:00    | -           | delayed     |
| 8     | 2 Nov 00:00    | 2 Nov 00:00 | 2 Nov 06:00    | -           | shipped     |

(*) the first second after the period.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.fulfillment import PickingTask
from app.models.inventory import StockReservation
from app.models.order import Order, OrderItem, OrderStatus
from app.models.shipment import Shipment
from app.models.user import RoleName
from app.services.dashboard_service import (
    DashboardService,
    DateRange,
    duration_kpi,
    rate_kpi,
)
from tests.factories import (
    auth_headers,
    create_bin,
    create_carrier,
    create_category,
    create_customer,
    create_product,
    create_user,
)

API = "/api/v1/dashboards/fulfillment"
PERIOD = DateRange(date(2026, 11, 1), date(2026, 11, 7))


def at(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text).replace(tzinfo=UTC) if text else None


@pytest.fixture()
def world(db_session: Session) -> None:
    customer = create_customer(db_session)
    carrier = create_carrier(db_session)
    product = create_product(db_session, create_category(db_session))
    bin_ = create_bin(db_session)
    orders: dict[int, Order] = {}

    def order(
        number, status, created, confirmed=None, shipped=None, delivered=None, **extra
    ):  # noqa: ANN001, ANN003, ANN202, E501
        o = Order(
            order_number=f"SO-2026-{number:06d}",
            customer_id=customer.id,
            status=status,
            ship_to_name="Chris",
            created_at=at(created),
            confirmed_at=at(confirmed),
            shipped_at=at(shipped),
            delivered_at=at(delivered),
            **extra,
        )
        db_session.add(o)
        db_session.flush()
        orders[number] = o

    order(1, "delivered", "2026-10-30T08:00", "2026-10-30T10:00", "2026-11-01T10:00", "2026-11-03T10:00")  # fmt: skip # noqa: E501
    order(2, "delivered", "2026-11-01T00:00", "2026-11-01T02:00", "2026-11-01T14:00", "2026-11-06T00:00")  # fmt: skip # noqa: E501
    order(3, "shipped", "2026-11-02T09:00", "2026-11-02T10:00", "2026-11-08T00:00")
    order(4, "cancelled", "2026-11-03T10:00", cancelled_at=at("2026-11-04T10:00"))
    order(5, "created", "2026-11-07T23:59:59")
    order(6, "backordered", "2026-10-31T23:59:59")
    order(7, "delayed", "2026-11-02T00:00", None, "2026-11-04T00:00")
    order(8, "shipped", "2026-11-02T00:00", "2026-11-02T00:00", "2026-11-02T06:00")

    def shipment(number, expected, delivered):  # noqa: ANN001, ANN202
        db_session.add(
            Shipment(
                order_id=orders[number].id,
                carrier_id=carrier.id,
                tracking_number=f"T{number}",
                status="delivered" if delivered else "dispatched",
                package_count=1,
                weight_kg=Decimal("1.000"),
                shipped_at=orders[number].shipped_at,
                expected_delivery_date=expected,
                delivered_at=at(delivered),
            )
        )

    shipment(1, date(2026, 11, 3), "2026-11-03T10:00")  # on time (on the day)
    shipment(2, date(2026, 11, 5), "2026-11-06T00:00")  # one day late
    shipment(3, date(2026, 11, 10), None)  # not delivered yet

    item = OrderItem(
        order_id=orders[1].id, line_number=1, product_id=product.id, quantity=1, unit_price=1
    )
    db_session.add(item)
    db_session.flush()

    def pick(status, completed, picked=None):  # noqa: ANN001, ANN202
        reservation = StockReservation(
            product_id=product.id, bin_id=bin_.id, quantity=1, status="fulfilled"
        )
        db_session.add(reservation)
        db_session.flush()
        db_session.add(
            PickingTask(
                order_id=orders[1].id,
                order_item_id=item.id,
                reservation_id=reservation.id,
                product_id=product.id,
                bin_id=bin_.id,
                quantity=1,
                quantity_picked=picked,
                sequence=1,
                status=status,
                completed_at=at(completed),
            )
        )

    pick("completed", "2026-10-31T23:59:59", 1)  # before the period
    pick("completed", "2026-11-01T00:00", 1)
    pick("short", "2026-11-03T10:00", 0)
    pick("completed", "2026-11-07T23:00", 1)
    pick("cancelled", "2026-11-02T10:00")  # never picked: not counted
    pick("completed", "2026-11-08T00:00", 1)  # after the period
    pick("pending", None)
    db_session.commit()


def test_fulfillment_kpis(db_session: Session, world: None) -> None:
    result = DashboardService(db_session).fulfillment(PERIOD)

    assert result.totals.model_dump() == {
        "placed": 6,  # 2, 3, 4, 5, 7, 8
        "shipped": 4,  # 1, 2, 7, 8 (3 ships after the period)
        "delivered": 2,  # 1, 2
        "cancelled": 1,  # 4
    }
    assert [(d.day.day, d.placed, d.shipped, d.delivered) for d in result.per_day] == [
        (1, 1, 2, 0),
        (2, 3, 1, 0),
        (3, 1, 0, 1),
        (4, 0, 1, 0),
        (5, 0, 0, 0),  # days without orders are listed too
        (6, 0, 0, 1),
        (7, 1, 0, 0),
    ]
    # Confirmed -> shipped: 48 h (1), 12 h (2), 6 h (8); 7 has no confirmation time
    assert result.fulfillment_time.model_dump() == {
        "orders": 3,
        "average_hours": Decimal("22.0"),
        "median_hours": Decimal("12.0"),
    }
    # Placed -> delivered: 98 h (1), 120 h (2)
    assert result.cycle_time.model_dump() == {
        "orders": 2,
        "average_hours": Decimal("109.0"),
        "median_hours": Decimal("109.0"),
    }
    assert result.on_time_delivery.model_dump() == {
        "good": 1,
        "total": 2,
        "percent": Decimal("50.0"),
    }
    assert result.picking_accuracy.model_dump() == {
        "good": 2,
        "total": 3,
        "percent": Decimal("66.7"),
    }
    counts = {s.status: s.count for s in result.by_status}
    assert [s.status for s in result.by_status] == [s.value for s in OrderStatus]
    assert {k: v for k, v in counts.items() if v} == {
        "delivered": 2,
        "shipped": 2,
        "cancelled": 1,
        "created": 1,
        "backordered": 1,
        "delayed": 1,
    }


def test_empty_period(db_session: Session) -> None:
    result = DashboardService(db_session).fulfillment(DateRange(date(2026, 1, 1), date(2026, 1, 2)))

    assert len(result.per_day) == 2
    assert result.totals.placed == 0
    assert result.fulfillment_time.average_hours is None
    assert result.cycle_time.median_hours is None
    assert result.on_time_delivery.percent is None
    assert result.picking_accuracy.percent is None
    assert sum(s.count for s in result.by_status) == 0


def test_duration_and_rate_helpers() -> None:
    from datetime import timedelta

    kpi = duration_kpi([timedelta(hours=h) for h in (4, 1, 2, 10)])
    assert (kpi.orders, kpi.average_hours, kpi.median_hours) == (
        4,
        Decimal("4.3"),  # 17 / 4 = 4.25, rounded half up
        Decimal("3.0"),  # (2 + 4) / 2
    )
    assert duration_kpi([timedelta(minutes=90)]).median_hours == Decimal("1.5")
    assert rate_kpi(2, 3).percent == Decimal("66.7")
    assert rate_kpi(0, 4).percent == Decimal("0.0")
    assert rate_kpi(0, 0).percent is None


def test_api_fulfillment(client: TestClient, db_session: Session, world: None) -> None:
    staff = create_user(db_session, "staff@example.com", roles=(RoleName.STAFF,))
    customer = create_user(db_session, "customer@example.com", roles=(RoleName.CUSTOMER,))
    params = {"date_from": "2026-11-01", "date_to": "2026-11-07"}

    body = client.get(API, params=params, headers=auth_headers(staff)).json()
    assert body["totals"]["placed"] == 6
    assert body["per_day"][0] == {"day": "2026-11-01", "placed": 1, "shipped": 2, "delivered": 0}
    assert body["on_time_delivery"]["percent"] == "50.0"
    assert client.get(API, headers=auth_headers(customer)).status_code == 403
    assert (
        client.get(
            API,
            params={"date_from": "2026-11-07", "date_to": "2026-11-01"},
            headers=auth_headers(staff),
        ).status_code
        == 422
    )
