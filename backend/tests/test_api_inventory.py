"""HTTP tests for /inventory, /cycle-counts and /alerts (permissions and full flows)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.catalog import Product
from app.models.user import RoleName, User
from app.models.warehouse import Bin
from tests.factories import auth_headers, create_bin, create_category, create_product, create_user

API = "/api/v1"
INV = f"{API}/inventory"


@pytest.fixture()
def users(db_session: Session) -> dict[str, User]:
    return {
        role.value: create_user(db_session, f"{role.value}@example.com", roles=(role,))
        for role in RoleName
    }


@pytest.fixture()
def h(users: dict[str, User]) -> dict[str, dict[str, str]]:
    """Auth headers per role: h["staff"], h["manager"], ..."""
    return {name: auth_headers(user) for name, user in users.items()}


@pytest.fixture()
def product(db_session: Session) -> Product:
    return create_product(db_session, create_category(db_session), sku="LAP-001", min_stock=5)


@pytest.fixture()
def bins(db_session: Session) -> dict[str, Bin]:
    return {
        "a": create_bin(db_session, "WH01-ZA-R01-S01-B01"),
        "b": create_bin(db_session, "WH01-ZA-R01-S01-B02"),
        "far": create_bin(db_session, "WH02-ZA-R01-S01-B01"),
    }


def receive(client: TestClient, headers: dict, product: Product, bin_: Bin, quantity: int):
    return client.post(
        f"{INV}/receive",
        json={"product_id": product.id, "bin_id": bin_.id, "quantity": quantity},
        headers=headers,
    )


# ------------------------------------------------------------------- permissions
@pytest.mark.parametrize(
    "url",
    [INV, f"{INV}/movements", f"{INV}/approvals", f"{API}/cycle-counts", f"{API}/alerts"],
)
def test_customers_and_anonymous_users_are_kept_out(client: TestClient, h: dict, url: str):
    assert client.get(url, headers=h["customer"]).status_code == 403
    assert client.get(url).status_code == 401


def test_staff_cannot_use_manager_actions(client: TestClient, h: dict, product, bins):
    staff = h["staff"]
    assert client.get(f"{INV}/approvals", headers=staff).status_code == 403
    reserve = {"product_id": product.id, "quantity": 1}
    assert client.post(f"{INV}/reservations", json=reserve, headers=staff).status_code == 403
    assert client.post(f"{INV}/adjustments/1/approve", headers=staff).status_code == 403
    assert client.post(f"{API}/alerts/1/acknowledge", headers=staff).status_code == 403
    assert client.post(f"{API}/cycle-counts/1/approve", headers=staff).status_code == 403


# ------------------------------------------------------------------ stock + history
def test_receive_list_and_product_stock(
    client: TestClient, db_session: Session, h: dict, users: dict, product, bins
):
    response = receive(client, h["staff"], product, bins["a"], 4)
    assert response.status_code == 201
    body = response.json()
    assert body["product"] == {"id": product.id, "sku": "LAP-001", "name": "Product LAP-001"}
    assert body["bin"]["location_code"] == "WH01-ZA-R01-S01-B01"
    assert (body["quantity_on_hand"], body["quantity_available"]) == (4, 4)
    receive(client, h["staff"], product, bins["b"], 3)

    listing = client.get(INV, params={"q": "b02"}, headers=h["manager"]).json()
    assert [row["bin"]["location_code"] for row in listing["items"]] == ["WH01-ZA-R01-S01-B02"]
    assert client.get(INV, params={"warehouse_id": 999}, headers=h["staff"]).json()["total"] == 0

    stock = client.get(f"{INV}/products/{product.id}", headers=h["staff"]).json()
    assert (stock["quantity_on_hand"], stock["quantity_available"]) == (7, 7)
    assert stock["is_low_stock"] is False
    assert [b["bin"]["id"] for b in stock["bins"]] == [bins["a"].id, bins["b"].id]
    assert client.get(f"{INV}/products/9999", headers=h["staff"]).status_code == 404

    movements = client.get(
        f"{INV}/movements", params={"bin_id": bins["a"].id}, headers=h["staff"]
    ).json()
    [movement] = movements["items"]
    assert movement["movement_type"] == "receipt"
    assert movement["created_by"]["email"] == "staff@example.com"

    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "inventory.receive"))
    assert audit.actor_id == users["staff"].id


def test_stock_errors_become_409_and_422(client: TestClient, h: dict, product, bins):
    staff = h["staff"]
    receive(client, staff, product, bins["a"], 2)

    too_many = client.post(
        f"{INV}/transfers",
        json={
            "product_id": product.id,
            "from_bin_id": bins["a"].id,
            "to_bin_id": bins["b"].id,
            "quantity": 5,
        },
        headers=staff,
    )
    assert too_many.status_code == 409
    assert too_many.json()["detail"] == ("Only 2 units of LAP-001 available in WH01-ZA-R01-S01-B01")
    unknown_bin = receive(client, staff, product, Bin(id=9999), 1)
    assert (unknown_bin.status_code, unknown_bin.json()["detail"]) == (422, "Bin not found")
    assert receive(client, staff, product, bins["a"], 0).status_code == 422


# ------------------------------------------------------------- approvals over HTTP
def test_staff_request_and_manager_approval(client: TestClient, h: dict, product, bins):
    receive(client, h["manager"], product, bins["a"], 10)
    request = client.post(
        f"{INV}/adjustments",
        json={
            "product_id": product.id,
            "bin_id": bins["a"].id,
            "kind": "decrease",
            "quantity": 3,
            "reason": "Missing after inventory",
        },
        headers=h["staff"],
    )
    assert request.status_code == 201
    assert request.json()["applied"] is False
    adjustment = request.json()["adjustment"]
    assert (adjustment["status"], adjustment["requested_by"]["email"]) == (
        "pending",
        "staff@example.com",
    )

    queue = client.get(f"{INV}/approvals", headers=h["manager"]).json()
    assert [a["id"] for a in queue["adjustments"]] == [adjustment["id"]]
    mine = client.get(
        f"{INV}/adjustments", params={"mine": True, "status": "pending"}, headers=h["staff"]
    ).json()
    assert mine["total"] == 1

    no_note = client.post(
        f"{INV}/adjustments/{adjustment['id']}/reject", json={}, headers=h["manager"]
    )
    assert no_note.status_code == 422

    approved = client.post(
        f"{INV}/adjustments/{adjustment['id']}/approve",
        json={"note": "OK"},
        headers=h["manager"],
    )
    assert approved.status_code == 200
    assert (approved.json()["status"], approved.json()["decided_by"]["email"]) == (
        "completed",
        "manager@example.com",
    )
    stock = client.get(f"{INV}/products/{product.id}", headers=h["staff"]).json()
    assert stock["quantity_on_hand"] == 7
    again = client.post(f"{INV}/adjustments/{adjustment['id']}/approve", headers=h["manager"])
    assert again.status_code == 409


def test_transfers_direct_and_across_warehouses(client: TestClient, h: dict, product, bins):
    receive(client, h["staff"], product, bins["a"], 10)

    def move(target: Bin, headers: dict):
        return client.post(
            f"{INV}/transfers",
            json={
                "product_id": product.id,
                "from_bin_id": bins["a"].id,
                "to_bin_id": target.id,
                "quantity": 2,
            },
            headers=headers,
        ).json()

    assert move(bins["b"], h["staff"])["applied"] is True
    cross = move(bins["far"], h["staff"])
    assert (cross["applied"], cross["transfer"]["status"]) == (False, "pending")

    cancelled = client.post(f"{INV}/transfers/{cross['transfer']['id']}/cancel", headers=h["staff"])
    assert cancelled.json()["status"] == "cancelled"
    listing = client.get(f"{INV}/transfers", params={"status": "completed"}, headers=h["staff"])
    assert listing.json()["total"] == 1


def test_manual_reservation_and_release(client: TestClient, h: dict, product, bins):
    receive(client, h["staff"], product, bins["a"], 10)

    created = client.post(
        f"{INV}/reservations",
        json={"product_id": product.id, "quantity": 4, "reason": "Trade fair"},
        headers=h["manager"],
    )
    assert created.status_code == 201
    [reservation] = created.json()
    assert (reservation["status"], reservation["quantity"]) == ("active", 4)

    active = client.get(f"{INV}/reservations", params={"status": "active"}, headers=h["staff"])
    assert active.json()["total"] == 1

    released = client.post(
        f"{INV}/reservations/{reservation['id']}/release", json={}, headers=h["manager"]
    )
    assert released.json()["status"] == "released"
    assert (
        client.post(
            f"{INV}/reservations/{reservation['id']}/release", headers=h["manager"]
        ).status_code
        == 409
    )


# ------------------------------------------------------------------ cycle counts
def test_cycle_count_flow(client: TestClient, h: dict, product, bins):
    receive(client, h["manager"], product, bins["a"], 10)
    staff, manager = h["staff"], h["manager"]

    started = client.post(f"{API}/cycle-counts", json={"bin_id": bins["a"].id}, headers=staff)
    assert started.status_code == 201
    count = started.json()
    assert [(line["product"]["sku"], line["expected_quantity"]) for line in count["lines"]] == [
        ("LAP-001", 10)
    ]

    recorded = client.put(
        f"{API}/cycle-counts/{count['id']}/lines",
        json={"lines": [{"product_id": product.id, "counted_quantity": 9}]},
        headers=staff,
    ).json()
    assert recorded["lines"][0]["variance"] == -1
    assert client.post(f"{API}/cycle-counts/{count['id']}/submit", headers=staff).json()[
        "status"
    ] == ("submitted")
    approved = client.post(f"{API}/cycle-counts/{count['id']}/approve", headers=manager)
    assert approved.json()["status"] == "completed"

    listing = client.get(f"{API}/cycle-counts", params={"status": "completed"}, headers=staff)
    assert listing.json()["items"][0]["bin"]["location_code"] == "WH01-ZA-R01-S01-B01"
    detail = client.get(f"{API}/cycle-counts/{count['id']}", headers=staff).json()
    assert detail["decided_by"]["email"] == "manager@example.com"
    assert client.get(f"{API}/cycle-counts/9999", headers=staff).status_code == 404


# ------------------------------------------------------------------------ alerts
def test_alerts_over_http(client: TestClient, h: dict, product, bins):
    receive(client, h["staff"], product, bins["a"], 2)  # below min_stock 5

    assert client.get(f"{API}/alerts/summary", headers=h["staff"]).json() == {"unresolved": 1}
    [alert] = client.get(f"{API}/alerts", params={"unresolved": True}, headers=h["staff"]).json()[
        "items"
    ]
    assert (alert["alert_type"], alert["product"]["sku"]) == ("low_stock", "LAP-001")

    acknowledged = client.post(f"{API}/alerts/{alert['id']}/acknowledge", headers=h["manager"])
    assert acknowledged.json()["acknowledged_by"]["email"] == "manager@example.com"
    resolved = client.post(f"{API}/alerts/{alert['id']}/resolve", headers=h["manager"])
    assert resolved.json()["status"] == "resolved"
    assert client.get(f"{API}/alerts/summary", headers=h["staff"]).json() == {"unresolved": 0}
    assert client.post(f"{API}/alerts/9999/resolve", headers=h["manager"]).status_code == 404
