"""Warehouse space use and supplier KPIs on hand-built data with known answers."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import Supplier
from app.models.inventory import Inventory, InventoryMovement
from app.models.purchase import PurchaseOrder, PurchaseOrderItem
from app.models.user import RoleName
from app.models.warehouse import Warehouse, Zone
from app.services.dashboard_service import DashboardService, DateRange
from tests.factories import (
    auth_headers,
    create_bin,
    create_category,
    create_product,
    create_supplier,
    create_user,
)

PERIOD = DateRange(date(2026, 11, 1), date(2026, 11, 7))
TODAY = date(2026, 11, 10)


def at(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text).replace(tzinfo=UTC) if text else None


# ========================================================================= warehouse
@pytest.fixture()
def layout(db_session: Session) -> None:
    """Zone ZA (picking): B01 with 10 x A, B02 empty, B03 archived with 5 x A.
    Zone ZB (bulk): B01 with 2 x B. Zone ZC (cold): no bins at all."""
    category = create_category(db_session)
    small = dict(weight_kg=Decimal("2.000"), length_cm=10, width_cm=10, height_cm=10)
    large = dict(weight_kg=Decimal("50.000"), length_cm=100, width_cm=50, height_cm=40)
    a = create_product(db_session, category, sku="A", **small)  # 2 kg, 1 000 cm³
    b = create_product(db_session, category, sku="B", **large)  # 50 kg, 200 000 cm³
    za1 = create_bin(db_session, "WH01-ZA-R01-S01-B01")
    za2 = create_bin(db_session, "WH01-ZA-R01-S01-B02")
    za3 = create_bin(db_session, "WH01-ZA-R01-S01-B03")
    za3.is_active = False
    zb1 = create_bin(
        db_session, "WH01-ZB-R01-S01-B01", max_weight_kg="400.000", max_volume_cm3=2_000_000
    )
    zb1.shelf.rack.zone.zone_type = "bulk"
    warehouse = za1.shelf.rack.zone.warehouse
    db_session.add(Zone(warehouse_id=warehouse.id, code="ZC", name="Cold", zone_type="cold"))

    for product, bin_, units in [(a, za1, 10), (a, za3, 5), (b, zb1, 2)]:
        db_session.add(
            Inventory(
                product_id=product.id,
                bin_id=bin_.id,
                quantity_on_hand=units,
                quantity_reserved=0,
                quantity_damaged=1 if product is b else 0,  # damaged units take space too
            )
        )
    db_session.add(  # an empty stock row does not make a bin occupied
        Inventory(
            product_id=b.id,
            bin_id=za2.id,
            quantity_on_hand=0,
            quantity_reserved=0,
            quantity_damaged=0,
        )
    )

    def move(product, bin_, kind, delta, when):  # noqa: ANN001, ANN202
        db_session.add(
            InventoryMovement(
                movement_type=kind,
                product_id=product.id,
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

    move(a, za1, "pick", -3, "2026-11-01T00:00")
    move(a, za1, "pick", -2, "2026-11-07T23:59:59")
    move(a, za3, "pick", -1, "2026-11-03T10:00")  # archived bin: still a pick in ZA
    move(a, za1, "adjustment", -4, "2026-11-03T10:00")  # not a pick
    move(b, zb1, "pick", -1, "2026-10-31T23:59:59")  # before the period
    move(b, zb1, "pick", -1, "2026-11-08T00:00")  # after the period
    db_session.commit()


def test_warehouse_space_and_picks(db_session: Session, layout: None) -> None:
    result = DashboardService(db_session).warehouse(PERIOD)

    # Active bins only: ZA B01, ZA B02, ZB B01
    assert result.total.model_dump() == {
        "bins": 3,
        "occupied_bins": 2,
        "occupancy_percent": Decimal("66.7"),
        "max_weight_kg": Decimal("600.000"),
        "used_weight_kg": Decimal("120.000"),  # 10 x 2 + 2 x 50
        "weight_percent": Decimal("20.0"),
        "max_volume_cm3": 4_000_000,
        "used_volume_cm3": Decimal("410000"),  # 10 x 1 000 + 2 x 200 000
        "volume_percent": Decimal("10.3"),  # 10.25, rounded half up
    }
    za, zb, zc = result.zones
    assert (za.code, za.zone_type, za.warehouse) == ("ZA", "picking", "WH01")
    assert (za.bins, za.occupied_bins, za.occupancy_percent) == (2, 1, Decimal("50.0"))
    assert (za.weight_percent, za.volume_percent) == (Decimal("10.0"), Decimal("0.5"))
    assert (za.picks, za.units_picked) == (3, 6)
    assert (zb.zone_type, zb.bins, zb.occupied_bins) == ("bulk", 1, 1)
    assert (zb.weight_percent, zb.volume_percent) == (Decimal("25.0"), Decimal("20.0"))
    assert (zb.picks, zb.units_picked) == (0, 0)
    assert zc.model_dump(include={"code", "bins", "occupancy_percent", "weight_percent"}) == {
        "code": "ZC",
        "bins": 0,
        "occupancy_percent": None,
        "weight_percent": None,
    }


def test_warehouse_without_layout(db_session: Session) -> None:
    result = DashboardService(db_session).warehouse(PERIOD)

    assert result.zones == []
    assert result.total.bins == 0
    assert result.total.volume_percent is None


# ========================================================================= suppliers
@pytest.fixture()
def purchasing(db_session: Session) -> dict[str, Supplier]:
    s1 = create_supplier(db_session, "SUP-001", lead_time_days=5)
    s2 = create_supplier(db_session, "SUP-002", lead_time_days=10)
    create_supplier(db_session, "SUP-003", is_active=False)  # no orders: not listed
    s4 = create_supplier(db_session, "SUP-004", is_active=False)  # archived, has an order
    warehouse = (
        db_session.scalar(select(Warehouse)) or create_bin(db_session).shelf.rack.zone.warehouse
    )
    product = create_product(db_session, create_category(db_session, "Purchasing"), sku="PO-1")
    numbers = iter(range(1, 100))

    def po(supplier, status, ordered, received, expected, lines=()):  # noqa: ANN001, ANN202
        order = PurchaseOrder(
            po_number=f"PO-2026-{next(numbers):06d}",
            supplier_id=supplier.id,
            warehouse_id=warehouse.id,
            status=status,
            ordered_at=at(ordered),
            received_at=at(received),
            expected_date=expected,
        )
        order.items = [
            PurchaseOrderItem(product_id=product.id, quantity=q, unit_cost=c, quantity_received=r)
            for q, c, r in lines
        ]
        db_session.add(order)

    # SUP-001: 5.0 days on time, 10.5 days late; one received before the period
    po(s1, "received", "2026-10-27T00:00", "2026-11-01T00:00", date(2026, 11, 1))
    po(s1, "received", "2026-10-25T00:00", "2026-11-04T12:00", date(2026, 11, 2))
    po(s1, "received", "2026-10-20T00:00", "2026-10-31T23:59:59", date(2026, 11, 1))
    # SUP-002: 6.0 days on time; one without an order time; two still open
    po(s2, "received", "2026-11-01T00:00", "2026-11-07T00:00", date(2026, 11, 7))
    po(s2, "received", None, "2026-11-05T00:00", date(2026, 11, 7))
    po(s2, "ordered", "2026-11-02T00:00", None, date(2026, 11, 9), [(10, Decimal("3.00"), 0)])
    po(s2, "partially_received", "2026-11-03T00:00", None, TODAY, [(4, Decimal("5.00"), 1)])
    po(s4, "draft", None, None, date(2026, 11, 20), [(1, Decimal("1.00"), 0)])
    db_session.commit()
    return {"s1": s1, "s2": s2, "s4": s4}


def test_supplier_kpis(db_session: Session, purchasing: dict) -> None:
    result = DashboardService(db_session).suppliers(PERIOD, include_financials=True, today=TODAY)

    # All suppliers: lead times 5.0, 10.5, 6.0 days
    assert result.model_dump(exclude={"period", "suppliers"}) == {
        "include_financials": True,
        "received_orders": 3,
        "lead_time_avg_days": Decimal("7.2"),  # 21.5 / 3
        "lead_time_variance": Decimal("5.72"),  # (4.69 + 11.11 + 1.36) / 3
        "lead_time_stddev_days": Decimal("2.4"),
        "on_time": {"good": 2, "total": 3, "percent": Decimal("66.7")},
        "open_orders": 2,
        "overdue_orders": 1,  # expected 9 Nov; the other is due today
        "open_value": Decimal("45.00"),  # 10 x 3.00 + 3 x 5.00 outstanding
    }
    assert [s.code for s in result.suppliers] == ["SUP-001", "SUP-002", "SUP-004"]
    s1, s2, s4 = result.suppliers
    assert s1.model_dump(exclude={"supplier_id", "name", "reliability_score"}) == {
        "code": "SUP-001",
        "is_active": True,
        "promised_lead_time_days": 5,
        "received_orders": 2,
        "lead_time_avg_days": Decimal("7.8"),  # 7.75, rounded half up
        "lead_time_variance": Decimal("7.56"),  # 2.75²
        "lead_time_stddev_days": Decimal("2.8"),
        "on_time": {"good": 1, "total": 2, "percent": Decimal("50.0")},
        "open_orders": 0,
        "overdue_orders": 0,
        "open_value": Decimal("0.00"),
    }
    assert (s2.received_orders, s2.lead_time_avg_days, s2.lead_time_variance) == (
        1,
        Decimal("6.0"),
        Decimal("0.00"),
    )
    assert (s2.open_orders, s2.overdue_orders, s2.open_value) == (2, 1, Decimal("45.00"))
    assert s2.on_time.percent == Decimal("100.0")
    assert (s4.is_active, s4.received_orders, s4.lead_time_avg_days, s4.open_orders) == (
        False,
        0,
        None,
        0,
    )
    assert s4.on_time.percent is None


def test_supplier_money_is_hidden_from_staff(db_session: Session, purchasing: dict) -> None:
    result = DashboardService(db_session).suppliers(PERIOD, include_financials=False, today=TODAY)

    assert result.open_value is None
    assert all(s.open_value is None for s in result.suppliers)
    assert result.overdue_orders == 1


# ------------------------------------------------------------------------------ API
def test_api_warehouse_and_suppliers(
    client: TestClient, db_session: Session, layout: None, purchasing: dict
) -> None:
    manager = create_user(db_session, "manager@example.com", roles=(RoleName.MANAGER,))
    staff = create_user(db_session, "staff@example.com", roles=(RoleName.STAFF,))
    customer = create_user(db_session, "customer@example.com", roles=(RoleName.CUSTOMER,))
    params = {"date_from": "2026-11-01", "date_to": "2026-11-07"}

    warehouse = client.get(
        "/api/v1/dashboards/warehouse", params=params, headers=auth_headers(staff)
    ).json()
    assert warehouse["zones"][0]["picks"] == 3
    assert warehouse["total"]["occupancy_percent"] == "66.7"

    url = "/api/v1/dashboards/suppliers"
    body = client.get(url, params=params, headers=auth_headers(manager)).json()
    assert body["received_orders"] == 3
    assert body["open_value"] == "45.00"
    hidden = client.get(url, params=params, headers=auth_headers(staff)).json()
    assert hidden["open_value"] is None
    for path in ("warehouse", "suppliers"):
        response = client.get(f"/api/v1/dashboards/{path}", headers=auth_headers(customer))
        assert response.status_code == 403
