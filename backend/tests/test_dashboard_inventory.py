"""Inventory KPIs on a hand-built stock and movement history with known answers.

Period: 1-7 Nov 2026 (7 days). Z1 sorts after the others by SKU
and "Kitchen" after "Food" by name, so the urgency and value orders are really tested.

| Product | Cost / price | Min | Now on hand (available) | Movements                          |
|---------|--------------|-----|-------------------------|------------------------------------|
| Z1      | 10 / 20      | 5   | 6 (6)                   | +20 30 Oct, -7 1 Nov 00:00 (pick),  |
|         |              |     |                         | -7 5 Nov (pick), +2 6 Nov (adjust), |
|         |              |     |                         | -2 8 Nov 00:00 (pick, after period) |
| P2      | 5 / 9        | 10  | 4 (3, one reserved)     | +10 1 Oct, -6 31 Oct 23:59 (pick)   |
| P3      | 2 / 3        | 0   | nothing                 | none                                |
| P4      | 1 / 2 (archived) | 0 | 5 (5)                  | none                                |
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.inventory import Inventory, InventoryMovement
from app.models.user import RoleName
from app.services.dashboard_service import DashboardService, DateRange, stock_status
from tests.factories import auth_headers, create_bin, create_category, create_product, create_user

API = "/api/v1/dashboards/inventory"
PERIOD = DateRange(date(2026, 11, 1), date(2026, 11, 7))


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.fixture()
def world(db_session: Session) -> None:
    kitchen = create_category(db_session, "Kitchen")
    food = create_category(db_session, "Food")

    def product(sku, category, cost, price, min_stock, **extra):  # noqa: ANN001, ANN202, ANN003
        return create_product(
            db_session,
            category,
            sku=sku,
            name=f"Product {sku}",
            unit_cost=Decimal(cost),
            unit_price=Decimal(price),
            min_stock=min_stock,
            **extra,
        )

    z1 = product("Z1", kitchen, "10.00", "20.00", 5)
    p2 = product("P2", kitchen, "5.00", "9.00", 10)
    product("P3", food, "2.00", "3.00", 0)
    p4 = product("P4", food, "1.00", "2.00", 0, is_active=False)
    bin_ = create_bin(db_session)

    def row(prod, on_hand, reserved=0):  # noqa: ANN001, ANN202
        db_session.add(
            Inventory(
                product_id=prod.id,
                bin_id=bin_.id,
                quantity_on_hand=on_hand,
                quantity_reserved=reserved,
                quantity_damaged=0,
            )
        )

    def move(prod, kind, delta, when):  # noqa: ANN001, ANN202
        db_session.add(
            InventoryMovement(
                movement_type=kind,
                product_id=prod.id,
                bin_id=bin_.id,
                quantity=abs(delta),
                on_hand_delta=delta,
                reserved_delta=0,
                damaged_delta=0,
                on_hand_after=0,
                reserved_after=0,
                damaged_after=0,
                created_at=at(when),
            )
        )

    row(z1, 6)
    row(p2, 4, reserved=1)
    row(p4, 5)
    move(z1, "receipt", 20, "2026-10-30T10:00:00")
    move(z1, "pick", -7, "2026-11-01T00:00:00")  # first second of the period
    move(z1, "pick", -7, "2026-11-05T10:00:00")
    move(z1, "adjustment", 2, "2026-11-06T10:00:00")  # not demand
    move(z1, "pick", -2, "2026-11-08T00:00:00")  # first second after the period
    move(p2, "receipt", 10, "2026-10-01T10:00:00")
    move(p2, "pick", -6, "2026-10-31T23:59:59")  # last second before the period
    db_session.commit()


def test_inventory_kpis(db_session: Session, world: None) -> None:
    result = DashboardService(db_session).inventory(PERIOD, include_financials=True)

    assert result.totals.model_dump() == {
        "value_at_cost": Decimal("85.00"),  # 6 x 10 + 4 x 5 + 5 x 1
        "value_at_price": Decimal("166.00"),  # 6 x 20 + 4 x 9 + 5 x 2
        "units_on_hand": 15,
        "units_available": 14,
        "units_reserved": 1,
        "units_damaged": 0,
        "units_picked": 14,  # Z1 only; the picks before and after the period do not count
    }
    # Cost picked 140; average stock value: Z1 (20 + 8) / 2 x 10 + P2 4 x 5 + P4 5 x 1 = 165
    assert result.turnover == Decimal("0.85")
    # Available value 6 x 10 + 3 x 5 + 5 x 1 = 80 at 140 / 7 = 20 per day
    assert result.days_of_supply == Decimal("4.0")
    assert result.stock_status.model_dump() == {"ok": 1, "low": 1, "out": 1}  # P4 archived
    assert [c.model_dump() for c in result.by_category] == [
        {
            "category_id": result.by_category[0].category_id,
            "category": "Kitchen",
            "products": 2,
            "units_on_hand": 10,
            "value_at_cost": Decimal("80.00"),
            "value_at_price": Decimal("156.00"),
        },
        {
            "category_id": result.by_category[1].category_id,
            "category": "Food",
            "products": 2,
            "units_on_hand": 5,
            "value_at_cost": Decimal("5.00"),
            "value_at_price": Decimal("10.00"),
        },
    ]

    assert result.products_total == 3
    z1, p2, p3 = result.products  # fewest days of supply first, then no demand by SKU
    assert (z1.sku, p2.sku, p3.sku) == ("Z1", "P2", "P3")
    assert z1.model_dump(exclude={"product_id", "name"}) == {
        "sku": "Z1",
        "category": "Kitchen",
        "status": "ok",
        "min_stock": 5,
        "units_on_hand": 6,
        "units_available": 6,
        "units_picked": 14,
        "avg_daily_demand": Decimal("2.00"),
        "days_of_supply": Decimal("3.0"),
        "turnover": Decimal("1.00"),  # 14 picked / average of 20 and 8
        "value_at_cost": Decimal("60.00"),
    }
    assert (p2.status, p2.units_available, p2.days_of_supply, p2.turnover) == (
        "low",
        3,
        None,  # no demand: lasts "forever"
        Decimal("0.00"),
    )
    assert (p3.status, p3.turnover, p3.days_of_supply) == ("out", None, None)  # no stock at all


def test_inventory_limit_and_hidden_money(db_session: Session, world: None) -> None:
    result = DashboardService(db_session).inventory(PERIOD, include_financials=False, limit=1)

    assert [p.sku for p in result.products] == ["Z1"]
    assert result.products_total == 3
    assert result.totals.value_at_cost is None
    assert result.totals.value_at_price is None
    assert all(c.value_at_cost is None and c.value_at_price is None for c in result.by_category)
    assert result.products[0].value_at_cost is None
    assert result.turnover == Decimal("0.85")  # ratios are not money


def test_period_after_the_last_movement_ends_with_current_stock(
    db_session: Session, world: None
) -> None:
    """Nothing moved after the period: its end stock is the current stock."""
    period = DateRange(date(2026, 11, 3), date(2026, 11, 9))
    result = DashboardService(db_session).inventory(period, include_financials=True)

    z1 = next(p for p in result.products if p.sku == "Z1")
    assert z1.units_picked == 9  # 7 on 5 Nov + 2 on 8 Nov
    # Start (3 Nov) 13, end 6: average 9.5
    assert z1.turnover == Decimal("0.95")


def test_empty_warehouse(db_session: Session) -> None:
    result = DashboardService(db_session).inventory(PERIOD, include_financials=True)

    assert result.totals.value_at_cost == Decimal("0.00")
    assert result.turnover is None
    assert result.days_of_supply is None
    assert result.products == []
    assert result.by_category == []


@pytest.mark.parametrize(
    ("available", "min_stock", "expected"),
    [(0, 0, "out"), (0, 5, "out"), (4, 5, "low"), (5, 5, "ok"), (3, 0, "ok")],
)
def test_stock_status(available: int, min_stock: int, expected: str) -> None:
    assert stock_status(available, min_stock) == expected


def test_api_inventory_by_role(client: TestClient, db_session: Session, world: None) -> None:
    manager = create_user(db_session, "manager@example.com", roles=(RoleName.MANAGER,))
    staff = create_user(db_session, "staff@example.com", roles=(RoleName.STAFF,))
    customer = create_user(db_session, "customer@example.com", roles=(RoleName.CUSTOMER,))
    params = {"date_from": "2026-11-01", "date_to": "2026-11-07"}

    body = client.get(API, params=params, headers=auth_headers(manager)).json()
    assert body["totals"]["value_at_cost"] == "85.00"
    assert body["totals"]["units_picked"] == 14
    assert body["by_category"][0]["category"] == "Kitchen"

    hidden = client.get(API, params={**params, "limit": 2}, headers=auth_headers(staff)).json()
    assert hidden["totals"]["value_at_price"] is None
    assert len(hidden["products"]) == 2
    assert client.get(API, headers=auth_headers(customer)).status_code == 403
    assert client.get(API, params={"limit": 0}, headers=auth_headers(manager)).status_code == 422
