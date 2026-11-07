"""Overview KPIs on a small, hand-built dataset whose answers are known in advance."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.exceptions import UnprocessableError
from app.models.audit import Alert
from app.models.inventory import Inventory
from app.models.order import Order
from app.models.purchase import PurchaseOrder, PurchaseOrderItem
from app.models.shipment import Shipment
from app.models.user import RoleName
from app.services.dashboard_service import DashboardService, DateRange
from tests.factories import (
    auth_headers,
    create_bin,
    create_carrier,
    create_category,
    create_customer,
    create_product,
    create_supplier,
    create_user,
)

API = "/api/v1/dashboards/overview"
PERIOD = DateRange(date(2026, 11, 1), date(2026, 11, 7))
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.fixture()
def world(db_session: Session) -> dict:
    category = create_category(db_session)
    a = create_product(db_session, category, sku="A", unit_cost=Decimal("10.00"), min_stock=5)
    b = create_product(db_session, category, sku="B", unit_cost=Decimal("2.50"), min_stock=0)
    c = create_product(db_session, category, sku="C", unit_cost=Decimal("100.00"), min_stock=2)
    d = create_product(
        db_session, category, sku="D", unit_cost=Decimal("1.00"), min_stock=10, is_active=False
    )
    bin1 = create_bin(db_session, "WH01-ZA-R01-S01-B01")
    archived = create_bin(db_session, "WH01-ZA-R01-S01-B02")
    archived.is_active = False

    def stock(product, bin_, on_hand, reserved=0, damaged=0):  # noqa: ANN001, ANN202
        db_session.add(
            Inventory(
                product_id=product.id,
                bin_id=bin_.id,
                quantity_on_hand=on_hand,
                quantity_reserved=reserved,
                quantity_damaged=damaged,
            )
        )

    stock(a, bin1, 10, reserved=3, damaged=1)  # 6 available
    stock(a, archived, 4)  # on hand, but not available
    stock(b, bin1, 20, reserved=20)  # nothing available
    stock(d, bin1, 3)  # archived product: value only

    customer = create_customer(db_session)
    carrier = create_carrier(db_session)

    def order(number, status, created, shipment=None):  # noqa: ANN001, ANN202
        o = Order(
            order_number=f"SO-2026-{number:06d}",
            customer_id=customer.id,
            status=status,
            ship_to_name="Chris",
            created_at=at(created),
        )
        db_session.add(o)
        db_session.flush()
        if shipment:
            ship_status, shipped, delivered = shipment
            db_session.add(
                Shipment(
                    order_id=o.id,
                    carrier_id=carrier.id,
                    tracking_number=f"T{number}",
                    status=ship_status,
                    package_count=1,
                    weight_kg=Decimal("1.000"),
                    shipped_at=at(shipped),
                    expected_delivery_date=date(2026, 11, 9),
                    delivered_at=at(delivered) if delivered else None,
                )
            )

    order(1, "created", "2026-10-31T23:59:59")  # before the period
    order(2, "backordered", "2026-11-01T00:00:00")  # first second of the period
    order(3, "on_hold", "2026-11-07T23:59:59")  # last second of the period
    order(4, "shipped", "2026-11-03T10:00:00", ("dispatched", "2026-11-07T08:00:00", None))
    order(
        5,
        "delivered",
        "2026-10-20T10:00:00",
        ("delivered", "2026-10-30T09:00:00", "2026-11-02T15:00:00"),
    )
    order(6, "cancelled", "2026-11-04T10:00:00")
    order(7, "delayed", "2026-11-05T10:00:00", ("delayed", "2026-11-05T16:00:00", None))
    order(8, "partially_allocated", "2026-11-08T00:00:00")  # after the period
    order(  # shipped at the first second after the period
        9,
        "delivered",
        "2026-10-25T10:00:00",
        ("delivered", "2026-11-08T00:00:00", "2026-11-09T10:00:00"),
    )

    for key, severity, status in [
        ("x:1", "critical", "open"),
        ("x:2", "warning", "acknowledged"),
        ("x:3", "critical", "resolved"),
    ]:
        db_session.add(
            Alert(
                alert_type="low_stock", dedup_key=key, severity=severity, status=status, title=key
            )
        )

    supplier = create_supplier(db_session)
    warehouse = bin1.shelf.rack.zone.warehouse

    def po(number, status, expected, lines):  # noqa: ANN001, ANN202
        p = PurchaseOrder(
            po_number=f"PO-2026-{number:06d}",
            supplier_id=supplier.id,
            warehouse_id=warehouse.id,
            status=status,
            expected_date=expected,
        )
        p.items = [
            PurchaseOrderItem(
                product_id=product.id, quantity=qty, unit_cost=cost, quantity_received=got
            )
            for product, qty, cost, got in lines
        ]
        db_session.add(p)

    po(1, "ordered", date(2026, 11, 6), [(a, 10, Decimal("5.00"), 0), (b, 4, Decimal("1.00"), 4)])
    po(2, "partially_received", date(2026, 11, 7), [(c, 3, Decimal("20.00"), 1)])
    po(3, "received", date(2026, 11, 1), [(a, 5, Decimal("5.00"), 5)])
    po(4, "draft", date(2026, 11, 1), [(a, 5, Decimal("5.00"), 0)])
    po(5, "cancelled", date(2026, 11, 1), [(a, 5, Decimal("5.00"), 0)])
    db_session.commit()
    return {"warehouse": warehouse}


def test_overview_kpis(db_session: Session, world: dict) -> None:
    result = DashboardService(db_session).overview(PERIOD, include_financials=True, now=NOW)

    assert result.period.model_dump() == {
        "date_from": date(2026, 11, 1),
        "date_to": date(2026, 11, 7),
        "days": 7,
    }
    assert result.inventory.model_dump() == {
        "value_at_cost": Decimal("193.00"),  # 14 x 10.00 + 20 x 2.50 + 3 x 1.00
        "units_on_hand": 37,
        "units_available": 9,  # A 6 (archived bin excluded), B 0, D 3
        "units_reserved": 23,
        "units_damaged": 1,
        "low_stock_products": 1,  # C; A has 6 >= 5; D is archived
        "out_of_stock_products": 2,  # B and C
    }
    assert result.orders.model_dump() == {
        "open": 4,  # 1, 2, 3, 8
        "backordered": 2,  # 2, 8
        "on_hold": 1,
        "placed_in_period": 5,  # 2, 3, 4, 6, 7
        "shipped_in_period": 2,  # 4, 7 (5 shipped before the period)
        "delivered_in_period": 1,  # 5
        "shipped_today": 1,  # 4
    }
    assert result.shipments.model_dump() == {"on_the_way": 2, "delayed": 1}
    assert result.alerts.model_dump() == {"unresolved": 2, "critical": 1}
    assert result.purchasing.model_dump() == {
        "open": 2,
        "overdue": 1,  # PO 1; PO 2 is due today
        "open_value": Decimal("90.00"),  # 10 x 5.00 + 2 x 20.00 still outstanding
    }


def test_overview_hides_money_without_financials(db_session: Session, world: dict) -> None:
    result = DashboardService(db_session).overview(PERIOD, include_financials=False, now=NOW)

    assert result.include_financials is False
    assert result.inventory.value_at_cost is None
    assert result.purchasing.open_value is None
    assert result.inventory.units_on_hand == 37  # the rest is the same


def test_overview_of_an_empty_warehouse(db_session: Session) -> None:
    result = DashboardService(db_session).overview(PERIOD, include_financials=True, now=NOW)

    assert result.inventory.value_at_cost == Decimal("0.00")
    assert result.inventory.units_on_hand == 0
    assert result.orders.open == 0
    assert result.purchasing.open_value == Decimal("0.00")


# ------------------------------------------------------------------- date range
TODAY = date(2026, 11, 7)


@pytest.mark.parametrize(
    ("date_from", "date_to", "expected"),
    [
        (None, None, (date(2026, 10, 9), TODAY)),  # the last 30 days
        (None, date(2026, 6, 30), (date(2026, 6, 1), date(2026, 6, 30))),
        (date(2026, 11, 1), None, (date(2026, 11, 1), TODAY)),
        (date(2026, 1, 1), date(2026, 1, 1), (date(2026, 1, 1), date(2026, 1, 1))),
        (date(2025, 11, 7), TODAY, (date(2025, 11, 7), TODAY)),  # 366 days
    ],
)
def test_date_range_defaults(
    date_from: date | None, date_to: date | None, expected: tuple[date, date]
) -> None:
    period = DateRange.resolve(date_from, date_to, today=TODAY)
    assert (period.date_from, period.date_to) == expected


@pytest.mark.parametrize(
    ("date_from", "date_to", "message"),
    [
        (date(2026, 11, 8), TODAY, "must not be after"),
        (date(2025, 11, 6), TODAY, "at most 366 days"),
    ],
)
def test_date_range_is_validated(date_from: date, date_to: date, message: str) -> None:
    with pytest.raises(UnprocessableError, match=message):
        DateRange.resolve(date_from, date_to, today=TODAY)


def test_date_range_bounds_are_utc_midnights() -> None:
    assert PERIOD.start == datetime(2026, 11, 1, tzinfo=UTC)
    assert PERIOD.end == datetime(2026, 11, 8, tzinfo=UTC)  # exclusive


# -------------------------------------------------------------------------- API
def test_api_overview_by_role(client: TestClient, db_session: Session, world: dict) -> None:
    users = {
        role: create_user(db_session, f"{role.value}@example.com", roles=(role,))
        for role in RoleName
    }
    params = {"date_from": "2026-11-01", "date_to": "2026-11-07"}

    manager = client.get(API, params=params, headers=auth_headers(users[RoleName.MANAGER]))
    assert manager.status_code == 200
    body = manager.json()
    assert body["include_financials"] is True
    assert body["inventory"]["value_at_cost"] == "193.00"
    assert body["orders"]["placed_in_period"] == 5
    assert body["period"] == {"date_from": "2026-11-01", "date_to": "2026-11-07", "days": 7}

    admin = client.get(API, params=params, headers=auth_headers(users[RoleName.ADMIN]))
    assert admin.json()["include_financials"] is True

    staff = client.get(API, params=params, headers=auth_headers(users[RoleName.STAFF])).json()
    assert staff["include_financials"] is False
    assert staff["inventory"]["value_at_cost"] is None
    assert staff["purchasing"]["open_value"] is None
    assert staff["orders"] == body["orders"]

    customer = client.get(API, headers=auth_headers(users[RoleName.CUSTOMER]))
    assert customer.status_code == 403
    assert client.get(API).status_code == 401


def test_api_rejects_bad_dates(client: TestClient, db_session: Session) -> None:
    headers = auth_headers(create_user(db_session, "m@example.com", roles=(RoleName.MANAGER,)))

    reversed_ = client.get(
        API, params={"date_from": "2026-11-07", "date_to": "2026-11-01"}, headers=headers
    )
    assert reversed_.status_code == 422
    assert "after the end date" in reversed_.text
    assert client.get(API, params={"date_from": "07.11.2026"}, headers=headers).status_code == 422
    assert client.get(API, headers=headers).json()["period"]["days"] == 30
