"""Scenario: stock corrections that need a manager's approval, through the API.

Staff may record losses and cross-warehouse transfers, but they only take effect once
a manager approves; a manager may also reject them (with a note), and staff may
withdraw their own requests. Unknown documents are a clean 404.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.factories import create_bin
from tests.integration.conftest import Warehouse, ok, stock

API = "/api/v1/inventory"


def stocked(client: TestClient, w: Warehouse) -> None:
    ok(
        client.post(
            f"{API}/receive",
            json={"product_id": w.laptop, "bin_id": w.pick_bin, "quantity": 10},
            headers=w.staff,
        ),
        201,
    )


def loss(client: TestClient, w: Warehouse, quantity: int) -> dict:
    """Staff report missing units: a pending request that changes nothing yet."""
    request = ok(
        client.post(
            f"{API}/adjustments",
            json={
                "product_id": w.laptop,
                "bin_id": w.pick_bin,
                "kind": "decrease",
                "quantity": quantity,
                "reason": "Not found on the shelf",
            },
            headers=w.staff,
        ),
        201,
    )
    assert request["applied"] is False and request["adjustment"]["status"] == "pending"
    return request["adjustment"]


def test_loss_reports_are_approved_rejected_or_withdrawn(client: TestClient, warehouse: Warehouse):
    w = warehouse
    stocked(client, w)

    rejected = loss(client, w, 3)
    assert (
        client.post(  # a rejection needs a note
            f"{API}/adjustments/{rejected['id']}/reject",
            json={"note": ""},
            headers=w.manager,
        ).status_code
        == 422
    )
    assert (
        client.post(  # staff cannot decide
            f"{API}/adjustments/{rejected['id']}/reject",
            json={"note": "Count again"},
            headers=w.staff,
        ).status_code
        == 403
    )
    body = ok(
        client.post(
            f"{API}/adjustments/{rejected['id']}/reject",
            json={"note": "Count again first"},
            headers=w.manager,
        )
    )
    assert body["status"] == "rejected"

    withdrawn = loss(client, w, 2)
    assert ok(client.post(f"{API}/adjustments/{withdrawn['id']}/cancel", headers=w.staff))[
        "status"
    ] == ("cancelled")
    assert stock(client, w.manager, w.laptop)["quantity_on_hand"] == 10  # nothing applied

    approved = loss(client, w, 4)
    assert ok(client.post(f"{API}/adjustments/{approved['id']}/approve", headers=w.manager))[
        "status"
    ] == (
        "completed"
    )  # approved and applied
    assert stock(client, w.manager, w.laptop)["quantity_on_hand"] == 6
    # A decided request cannot be decided again.
    again = client.post(
        f"{API}/adjustments/{approved['id']}/reject",
        json={"note": "Too late"},
        headers=w.manager,
    )
    assert again.status_code == 409


def test_cross_warehouse_transfers_need_approval(
    client: TestClient, db_session: Session, warehouse: Warehouse
):
    w = warehouse
    stocked(client, w)
    other = create_bin(db_session, "WH02-ZA-R01-S01-B01")

    def request(quantity: int) -> dict:
        body = ok(
            client.post(
                f"{API}/transfers",
                json={
                    "product_id": w.laptop,
                    "from_bin_id": w.pick_bin,
                    "to_bin_id": other.id,
                    "quantity": quantity,
                },
                headers=w.staff,
            ),
            201,
        )
        assert body["applied"] is False and body["transfer"]["status"] == "pending"
        return body["transfer"]

    first = request(2)
    ok(
        client.post(
            f"{API}/transfers/{first['id']}/reject",
            json={"note": "WH02 is full this week"},
            headers=w.manager,
        )
    )
    second = request(3)
    approved = ok(
        client.post(
            f"{API}/transfers/{second['id']}/approve",
            json={"note": "OK"},
            headers=w.manager,
        )
    )
    assert approved["status"] == "completed"  # approved and applied
    rows = ok(client.get(f"{API}", params={"product_id": w.laptop}, headers=w.manager))["items"]
    assert {row["bin"]["id"]: row["quantity_on_hand"] for row in rows} == {
        w.pick_bin: 7,
        other.id: 3,
    }
    third = request(1)
    ok(client.post(f"{API}/transfers/{third['id']}/cancel", headers=w.staff))


def test_unknown_documents_are_not_found(client: TestClient, warehouse: Warehouse):
    w = warehouse
    for path, body in (
        ("adjustments/999/approve", None),
        ("adjustments/999/reject", {"note": "No such request"}),
        ("adjustments/999/cancel", None),
        ("transfers/999/approve", None),
        ("transfers/999/reject", {"note": "No such request"}),
        ("transfers/999/cancel", None),
    ):
        assert client.post(f"{API}/{path}", json=body, headers=w.manager).status_code == 404, path
