"""Supplier purchase orders: drafting, ordering, receiving into bins, overdue alerts."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, UnprocessableError
from app.models.audit import Alert, AlertStatus, AlertType, AuditLog
from app.models.catalog import SupplierProduct
from app.models.inventory import Inventory, InventoryMovement, MovementType
from app.models.purchase import PurchaseOrder, PurchaseOrderStatus
from app.models.user import RoleName
from app.schemas.purchase import PurchaseOrderCreate, PurchaseOrderReceipt
from app.services.inventory_service import CapacityExceededError
from app.services.purchase_order_service import PurchaseOrderService, overdue_key
from tests.factories import (
    auth_headers,
    create_bin,
    create_category,
    create_product,
    create_supplier,
    create_user,
)

API = "/api/v1"
TODAY = datetime.now(UTC).date()


@pytest.fixture()
def world(db_session: Session) -> dict:
    category = create_category(db_session)
    lap = create_product(db_session, category, sku="LAP-001", min_stock=5)
    mou = create_product(db_session, category, sku="MOU-001", unit_cost=Decimal("8.00"))
    supplier = create_supplier(db_session, "SUP-001", lead_time_days=5)
    db_session.add(
        SupplierProduct(
            supplier_id=supplier.id,
            product_id=lap.id,
            unit_cost=Decimal("550.00"),
            lead_time_days=10,
            min_order_qty=2,
        )
    )
    bin_a = create_bin(db_session, "WH01-ZA-R01-S01-B01")
    bin_b = create_bin(db_session, "WH01-ZA-R01-S01-B02")
    other_wh = create_bin(db_session, "WH02-ZA-R01-S01-B01")
    manager = create_user(db_session, "manager@example.com", roles=(RoleName.MANAGER,))
    db_session.commit()
    return {
        "lap": lap,
        "mou": mou,
        "supplier": supplier,
        "bins": {"a": bin_a, "b": bin_b, "other": other_wh},
        "warehouse": bin_a.shelf.rack.zone.warehouse,
        "manager": manager,
    }


def _draft(db: Session, w: dict, **overrides: object) -> PurchaseOrder:
    data = {
        "supplier_id": w["supplier"].id,
        "warehouse_id": w["warehouse"].id,
        "items": [
            {"product_id": w["lap"].id, "quantity": 10},
            {"product_id": w["mou"].id, "quantity": 20},
        ],
        **overrides,
    }
    return PurchaseOrderService(db).create(PurchaseOrderCreate(**data), user=w["manager"])


def _receipt(*lines: tuple[int, int, int]) -> PurchaseOrderReceipt:
    return PurchaseOrderReceipt(
        items=[{"product_id": p, "quantity": q, "bin_id": b} for p, q, b in lines]
    )


# ------------------------------------------------------------------------- create
def test_create_uses_supplier_prices_and_lead_time(db_session: Session, world: dict) -> None:
    po = _draft(db_session, world)
    assert po.po_number == f"PO-{TODAY.year}-000001"
    assert po.status == PurchaseOrderStatus.DRAFT
    costs = {i.product.sku: i.unit_cost for i in po.items}
    assert costs == {
        "LAP-001": Decimal("550.00"),
        "MOU-001": Decimal("8.00"),
    }  # offer, product
    assert po.total_cost == Decimal("5660.00")
    assert po.expected_date == TODAY + timedelta(days=10)  # longest lead time of the lines
    assert _draft(db_session, world).po_number.endswith("000002")
    assert db_session.scalar(select(AuditLog).where(AuditLog.action == "purchase_order.create"))


def test_create_explicit_cost_and_date(db_session: Session, world: dict) -> None:
    po = _draft(
        db_session,
        world,
        expected_date=TODAY + timedelta(days=3),
        items=[{"product_id": world["lap"].id, "quantity": 4, "unit_cost": "500.00"}],
    )
    assert po.items[0].unit_cost == Decimal("500.00")
    assert po.expected_date == TODAY + timedelta(days=3)


def test_create_without_offer_uses_supplier_lead_time(db_session: Session, world: dict) -> None:
    po = _draft(db_session, world, items=[{"product_id": world["mou"].id, "quantity": 1}])
    assert po.expected_date == TODAY + timedelta(days=5)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"items": [{"product_id": 0, "quantity": 1}]}, "Product not found"),
        ({"warehouse_id": 999}, "Warehouse"),
        ({"supplier_id": 999}, "Supplier not found"),
        ({"expected_date": date(2020, 1, 1)}, "past"),
    ],
)
def test_create_refuses_bad_input(
    db_session: Session, world: dict, overrides: dict, message: str
) -> None:
    with pytest.raises(UnprocessableError, match=message):
        _draft(db_session, world, **overrides)


def test_create_respects_min_order_qty(db_session: Session, world: dict) -> None:
    with pytest.raises(UnprocessableError, match="at least 2"):
        _draft(db_session, world, items=[{"product_id": world["lap"].id, "quantity": 1}])


def test_create_refuses_archived_supplier(db_session: Session, world: dict) -> None:
    world["supplier"].is_active = False
    db_session.commit()
    with pytest.raises(UnprocessableError, match="archived"):
        _draft(db_session, world)


def test_duplicate_products_are_refused() -> None:
    with pytest.raises(ValueError, match="only once"):
        PurchaseOrderCreate(
            supplier_id=1,
            warehouse_id=1,
            items=[{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 2}],
        )


# ---------------------------------------------------------------- order / cancel
def test_order_then_cancel(db_session: Session, world: dict) -> None:
    service = PurchaseOrderService(db_session)
    po = _draft(db_session, world)
    service.order(po.id, user=None)
    assert po.status == PurchaseOrderStatus.ORDERED
    assert po.ordered_at is not None
    with pytest.raises(ConflictError, match="only draft"):
        service.order(po.id, user=None)
    service.cancel(po.id, user=None)
    assert po.status == PurchaseOrderStatus.CANCELLED
    with pytest.raises(ConflictError):
        service.cancel(po.id, user=None)
    with pytest.raises(ConflictError, match="only ordered goods"):
        service.receive(po.id, _receipt((world["lap"].id, 1, world["bins"]["a"].id)), user=None)


def test_draft_cannot_be_received(db_session: Session, world: dict) -> None:
    po = _draft(db_session, world)
    with pytest.raises(ConflictError, match="draft"):
        PurchaseOrderService(db_session).receive(
            po.id, _receipt((world["lap"].id, 1, world["bins"]["a"].id)), user=None
        )


# ------------------------------------------------------------------------ receive
def _ordered(db: Session, w: dict) -> PurchaseOrder:
    po = _draft(db, w)
    return PurchaseOrderService(db).order(po.id, user=w["manager"])


def _on_hand(db: Session, product_id: int, bin_id: int) -> int:
    row = db.scalar(select(Inventory).filter_by(product_id=product_id, bin_id=bin_id))
    return row.quantity_on_hand if row else 0


def test_partial_then_full_receipt(db_session: Session, world: dict) -> None:
    service = PurchaseOrderService(db_session)
    po = _ordered(db_session, world)
    lap, mou, bins = world["lap"], world["mou"], world["bins"]

    service.receive(
        po.id, _receipt((lap.id, 4, bins["a"].id), (lap.id, 2, bins["b"].id)), user=None
    )
    assert po.status == PurchaseOrderStatus.PARTIALLY_RECEIVED
    assert [i.quantity_received for i in po.items] == [6, 0]
    assert _on_hand(db_session, lap.id, bins["a"].id) == 4
    assert _on_hand(db_session, lap.id, bins["b"].id) == 2
    movements = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.movement_type == MovementType.RECEIPT)
    ).all()
    assert len(movements) == 2
    assert all(po.po_number in (m.reason or "") for m in movements)
    with pytest.raises(ConflictError):  # goods arrived: cannot be cancelled any more
        service.cancel(po.id, user=None)

    service.receive(
        po.id,
        _receipt((lap.id, 4, bins["a"].id), (mou.id, 20, bins["b"].id)),
        user=None,
    )
    assert po.status == PurchaseOrderStatus.RECEIVED
    assert po.received_at is not None
    assert _on_hand(db_session, lap.id, bins["a"].id) == 8
    assert _on_hand(db_session, mou.id, bins["b"].id) == 20


def test_cannot_receive_more_than_outstanding(db_session: Session, world: dict) -> None:
    service = PurchaseOrderService(db_session)
    po = _ordered(db_session, world)
    lap, bins = world["lap"], world["bins"]
    with pytest.raises(UnprocessableError, match="only 10"):
        service.receive(
            po.id,
            _receipt((lap.id, 6, bins["a"].id), (lap.id, 5, bins["b"].id)),
            user=None,
        )
    service.receive(po.id, _receipt((lap.id, 10, bins["a"].id)), user=None)
    with pytest.raises(UnprocessableError, match="only 0"):
        service.receive(po.id, _receipt((lap.id, 1, bins["a"].id)), user=None)


def test_receive_refuses_unknown_product_and_foreign_bin(db_session: Session, world: dict) -> None:
    service = PurchaseOrderService(db_session)
    po = _ordered(db_session, world)
    with pytest.raises(UnprocessableError, match="not part of"):
        service.receive(po.id, _receipt((999, 1, world["bins"]["a"].id)), user=None)
    with pytest.raises(UnprocessableError, match="not in warehouse"):
        service.receive(po.id, _receipt((world["lap"].id, 1, world["bins"]["other"].id)), user=None)


def test_failed_receipt_changes_nothing(db_session: Session, world: dict) -> None:
    """The second line does not fit: the first line's stock is not kept either."""
    service = PurchaseOrderService(db_session)
    po = _ordered(db_session, world)
    tiny = create_bin(db_session, "WH01-ZA-R01-S01-B09", max_weight_kg="0.001")
    with pytest.raises(CapacityExceededError, match="do not fit"):
        service.receive(
            po.id,
            _receipt(
                (world["mou"].id, 5, world["bins"]["a"].id),
                (world["lap"].id, 2, tiny.id),
            ),
            user=None,
        )
    db_session.commit()  # would write anything the failed receipt left behind
    db_session.expire_all()
    assert _on_hand(db_session, world["mou"].id, world["bins"]["a"].id) == 0
    assert all(i.quantity_received == 0 for i in service.get(po.id).items)
    assert service.get(po.id).status == PurchaseOrderStatus.ORDERED


def test_receipt_resolves_low_stock_alert(db_session: Session, world: dict) -> None:
    """LAP-001 has min_stock 5 and no stock; receiving 6 units resolves the alert."""
    from app.services.alert_service import AlertService, low_stock_key

    AlertService(db_session).evaluate(product_ids=[world["lap"].id])
    db_session.commit()
    po = _ordered(db_session, world)
    PurchaseOrderService(db_session).receive(
        po.id, _receipt((world["lap"].id, 6, world["bins"]["a"].id)), user=None
    )
    alert = db_session.scalar(
        select(Alert).where(Alert.dedup_key == low_stock_key(world["lap"].id))
    )
    assert alert is not None
    assert alert.status == AlertStatus.RESOLVED


# ------------------------------------------------------------------------ overdue
def _overdue_alert(db: Session, po: PurchaseOrder) -> Alert | None:
    return db.scalar(select(Alert).where(Alert.dedup_key == overdue_key(po.id)))


def test_overdue_alert_raised_and_resolved_on_full_receipt(
    db_session: Session, world: dict
) -> None:
    service = PurchaseOrderService(db_session)
    po = _ordered(db_session, world)
    draft = _draft(db_session, world)  # drafts are never overdue
    assert service.check_overdue(today=po.expected_date) == []  # due today: not late yet

    late = service.check_overdue(today=po.expected_date + timedelta(days=3))
    assert late == [po]
    assert draft not in late
    alert = _overdue_alert(db_session, po)
    assert alert.alert_type == AlertType.OVERDUE_SUPPLIER
    assert alert.severity == "warning"
    assert "3 day(s) late with 30 unit(s)" in alert.message
    service.check_overdue(today=po.expected_date + timedelta(days=8))
    assert alert.severity == "critical"  # same alert, updated
    assert len(db_session.scalars(select(Alert)).all()) == 1

    lap, mou, bins = world["lap"], world["mou"], world["bins"]
    service.receive(po.id, _receipt((lap.id, 10, bins["a"].id)), user=None)
    assert alert.status == AlertStatus.OPEN  # still waiting for the mice
    service.receive(po.id, _receipt((mou.id, 20, bins["b"].id)), user=None)
    assert alert.status == AlertStatus.RESOLVED


def test_cancel_resolves_overdue_alert(db_session: Session, world: dict) -> None:
    service = PurchaseOrderService(db_session)
    po = _ordered(db_session, world)
    service.check_overdue(today=po.expected_date + timedelta(days=1))
    service.cancel(po.id, user=None)
    assert _overdue_alert(db_session, po).status == AlertStatus.RESOLVED


def test_is_overdue_property(db_session: Session, world: dict) -> None:
    po = _ordered(db_session, world)
    assert po.is_overdue is False
    po.expected_date = TODAY - timedelta(days=1)
    assert po.is_overdue is True
    po.status = PurchaseOrderStatus.RECEIVED
    assert po.is_overdue is False


# ---------------------------------------------------------------------------- API
def test_api_flow_and_permissions(client: TestClient, db_session: Session, world: dict) -> None:
    staff = create_user(db_session, "staff@example.com", roles=(RoleName.STAFF,))
    customer = create_user(db_session, "customer@example.com", roles=(RoleName.CUSTOMER,))
    hm, hs, hc = (auth_headers(u) for u in (world["manager"], staff, customer))
    body = {
        "supplier_id": world["supplier"].id,
        "warehouse_id": world["warehouse"].id,
        "notes": "Restock before the sale",
        "items": [{"product_id": world["lap"].id, "quantity": 4}],
    }
    assert client.post(f"{API}/purchase-orders", json=body, headers=hs).status_code == 403
    created = client.post(f"{API}/purchase-orders", json=body, headers=hm)
    assert created.status_code == 201
    po = created.json()
    assert po["supplier"]["code"] == "SUP-001"
    assert po["warehouse"]["code"] == "WH01"
    assert po["total_cost"] == "2200.00"
    assert po["items"][0]["quantity_outstanding"] == 4
    assert po["created_by"]["email"] == "manager@example.com"
    url = f"{API}/purchase-orders/{po['id']}"

    assert client.get(url, headers=hc).status_code == 403
    assert client.get(f"{API}/purchase-orders", headers=hc).status_code == 403
    assert client.post(f"{url}/order", headers=hs).status_code == 403
    assert client.post(f"{url}/order", headers=hm).json()["status"] == "ordered"
    assert client.post(f"{url}/order", headers=hm).status_code == 409

    receipt = {
        "items": [
            {
                "product_id": world["lap"].id,
                "quantity": 4,
                "bin_id": world["bins"]["a"].id,
            }
        ]
    }
    assert client.post(f"{url}/receive", json=receipt, headers=hc).status_code == 403
    received = client.post(f"{url}/receive", json=receipt, headers=hs)
    assert received.status_code == 200
    assert received.json()["status"] == "received"
    assert client.post(f"{url}/cancel", headers=hm).status_code == 409

    listing = client.get(f"{API}/purchase-orders", params={"status": "received"}, headers=hs)
    assert listing.json()["total"] == 1
    assert (
        client.get(f"{API}/purchase-orders", params={"q": "nothing"}, headers=hs).json()["total"]
        == 0
    )
    assert (
        client.get(f"{API}/purchase-orders", params={"q": "Supplier SUP"}, headers=hs).json()[
            "total"
        ]
        == 1
    )
    assert client.get(f"{API}/purchase-orders/999", headers=hs).status_code == 404


def test_api_overdue_listing_and_check(
    client: TestClient, db_session: Session, world: dict
) -> None:
    hm = auth_headers(world["manager"])
    late = _ordered(db_session, world)
    on_time = _ordered(db_session, world)
    late.expected_date = TODAY - timedelta(days=2)
    db_session.commit()

    listing = client.get(f"{API}/purchase-orders", params={"overdue": True}, headers=hm).json()
    assert [p["po_number"] for p in listing["items"]] == [late.po_number]
    assert listing["items"][0]["is_overdue"] is True
    assert on_time.is_overdue is False

    checked = client.post(f"{API}/purchase-orders/check-overdue", headers=hm)
    assert [p["id"] for p in checked.json()] == [late.id]
    assert _overdue_alert(db_session, late) is not None
    staff = create_user(db_session, "staff@example.com", roles=(RoleName.STAFF,))
    assert (
        client.post(f"{API}/purchase-orders/check-overdue", headers=auth_headers(staff)).status_code
        == 403
    )
