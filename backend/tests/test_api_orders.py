"""HTTP tests for orders, fulfillment, shipments and returns.

The first test is the end-to-end integration test of the project document: one order
from creation to delivery and return, checking stock and movements after every step.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.inventory import InventoryMovement
from app.models.user import RoleName
from app.models.warehouse import Bin
from tests.factories import (
    auth_headers,
    create_bin,
    create_carrier,
    create_category,
    create_customer,
    create_product,
    create_user,
)

API = "/api/v1"


@pytest.fixture()
def world(db_session: Session) -> dict:
    """Users, two customers (one linked to a login), two products, bins and a carrier."""
    users = {
        role.value: create_user(db_session, f"{role.value}@example.com", roles=(role,))
        for role in RoleName
    }
    users["other"] = create_user(db_session, "other@example.com", roles=(RoleName.CUSTOMER,))
    users["unlinked"] = create_user(db_session, "nobody@example.com", roles=(RoleName.CUSTOMER,))
    mine = create_customer(db_session, "CUST-0001", name="Chris", user_id=users["customer"].id)
    other = create_customer(db_session, "CUST-0002", name="Other", user_id=users["other"].id)
    category = create_category(db_session)
    lap = create_product(db_session, category, sku="LAP-001", unit_price=Decimal("899.00"))
    mou = create_product(db_session, category, sku="MOU-001", unit_price=Decimal("24.90"))
    pick_a = create_bin(db_session, "WH01-ZA-R01-S01-B01")
    pick_b = create_bin(db_session, "WH01-ZA-R02-S01-B01")
    returns = create_bin(db_session, "WH01-ZR-R01-S01-B01")
    returns.shelf.rack.zone.zone_type = "returns"
    db_session.commit()
    carrier = create_carrier(db_session, "DHL", default_transit_days=2)
    return {
        "users": users,
        "h": {name: auth_headers(user) for name, user in users.items()},
        "customer": mine,
        "other_customer": other,
        "lap": lap,
        "mou": mou,
        "bins": {"a": pick_a, "b": pick_b, "returns": returns},
        "carrier": carrier,
    }


def receive(client: TestClient, w: dict, product, bin_: Bin, quantity: int) -> None:
    response = client.post(
        f"{API}/inventory/receive",
        json={"product_id": product.id, "bin_id": bin_.id, "quantity": quantity},
        headers=w["h"]["staff"],
    )
    assert response.status_code == 201, response.text


def stock(client: TestClient, w: dict, product) -> dict:
    body = client.get(f"{API}/inventory/products/{product.id}", headers=w["h"]["staff"]).json()
    return {
        "on_hand": body["quantity_on_hand"],
        "reserved": body["quantity_reserved"],
        "damaged": body["quantity_damaged"],
        "available": body["quantity_available"],
    }


def place_order(client: TestClient, w: dict, lines, who: str = "customer", customer=None) -> dict:
    customer = customer or w["customer"]
    response = client.post(
        f"{API}/orders",
        json={
            "customer_id": customer.id,
            "items": [{"product_id": p.id, "quantity": q} for p, q in lines],
        },
        headers=w["h"][who],
    )
    assert response.status_code == 201, response.text
    return response.json()


# ============================================================================ end to end
def test_order_from_creation_to_delivery_and_return(
    client: TestClient, db_session: Session, world: dict
):
    w, h = world, world["h"]
    lap, mou = w["lap"], w["mou"]
    receive(client, w, lap, w["bins"]["a"], 1)  # 1 here (the picker will find none)...
    receive(client, w, lap, w["bins"]["b"], 4)  # ...and 4 here
    receive(client, w, mou, w["bins"]["a"], 10)

    # 1. The customer places and confirms the order: stock is reserved
    order = place_order(client, w, [(lap, 2), (mou, 3)])
    assert (order["status"], order["subtotal"]) == ("created", "1872.70")
    assert order["next_statuses"] == ["confirmed", "on_hold", "cancelled"]
    order = client.post(f"{API}/orders/{order['id']}/confirm", headers=h["customer"]).json()
    assert order["status"] == "inventory_reserved"
    assert stock(client, w, lap) == {"on_hand": 5, "reserved": 2, "damaged": 0, "available": 3}

    # 2. A manager allocates: a picking route
    tasks = client.post(f"{API}/orders/{order['id']}/allocate", headers=h["manager"]).json()
    route = [(t["sequence"], t["bin"]["location_code"], t["product"]["sku"]) for t in tasks]
    assert route == [  # same distance to packing: by rack code
        (1, "WH01-ZA-R01-S01-B01", "LAP-001"),
        (2, "WH01-ZA-R01-S01-B01", "MOU-001"),
        (3, "WH01-ZA-R02-S01-B01", "LAP-001"),
    ]
    queue = client.get(f"{API}/picking-tasks", headers=h["staff"]).json()
    assert queue["total"] == len(tasks)

    # 3. Staff pick; the laptop in bin A is missing (short pick)
    for task in tasks:
        assert (
            client.post(f"{API}/picking-tasks/{task['id']}/start", headers=h["staff"]).status_code
            == 200
        )
        short = task["product"]["sku"] == "LAP-001" and task["bin"]["id"] == w["bins"]["a"].id
        response = client.post(
            f"{API}/picking-tasks/{task['id']}/complete",
            json={
                "bin_code": task["bin"]["location_code"].lower(),
                "product_code": task["product"]["sku"],
                "quantity_picked": 0 if short else task["quantity"],
                "short_reason": "Bin was empty" if short else None,
            },
            headers=h["staff"],
        )
        assert response.status_code == 200, response.text
    # The short laptop was replaced from bin B: one more task on the route
    open_tasks = client.get(
        f"{API}/picking-tasks", params={"order_id": order["id"]}, headers=h["staff"]
    ).json()["items"]
    assert len(open_tasks) == 1 and open_tasks[0]["bin"]["id"] == w["bins"]["b"].id
    replacement = open_tasks[0]
    client.post(f"{API}/picking-tasks/{replacement['id']}/start", headers=h["staff"])
    client.post(
        f"{API}/picking-tasks/{replacement['id']}/complete",
        json={
            "bin_code": replacement["bin"]["location_code"],
            "product_code": "LAP-001",
            "quantity_picked": replacement["quantity"],
        },
        headers=h["staff"],
    )
    order = client.get(f"{API}/orders/{order['id']}", headers=h["manager"]).json()
    assert order["status"] == "picked"
    # Picking reduced stock: 2 laptops left the warehouse, 1 phantom laptop was written off
    assert stock(client, w, lap) == {"on_hand": 2, "reserved": 0, "damaged": 0, "available": 2}
    assert stock(client, w, mou) == {"on_hand": 7, "reserved": 0, "damaged": 0, "available": 7}

    # 4. Packing
    [packing] = client.get(f"{API}/packing-tasks", headers=h["staff"]).json()["items"]
    assert [(line["product"]["sku"], line["quantity_picked"]) for line in packing["lines"]] == [
        ("LAP-001", 2),
        ("MOU-001", 3),
    ]
    client.post(f"{API}/packing-tasks/{packing['id']}/start", headers=h["staff"])
    packed = client.post(
        f"{API}/packing-tasks/{packing['id']}/complete",
        json={
            "items": [
                {"product_id": lap.id, "quantity": 2},
                {"product_id": mou.id, "quantity": 3},
            ],
            "package_count": 1,
            "weight_kg": "4.5",
        },
        headers=h["staff"],
    )
    assert packed.json()["status"] == "completed"

    # 5. Shipping, a delay, and delivery
    shipment = client.post(
        f"{API}/shipments",
        json={"order_id": order["id"], "carrier_id": w["carrier"].id},
        headers=h["staff"],
    ).json()
    assert shipment["status"] == "dispatched" and shipment["tracking_url"]
    client.post(
        f"{API}/shipments/{shipment['id']}/events",
        json={"event_type": "delayed", "description": "Storm"},
        headers=h["staff"],
    )
    assert client.get(f"{API}/alerts/summary", headers=h["manager"]).json()["unresolved"] >= 1
    delivered = client.post(
        f"{API}/shipments/{shipment['id']}/events",
        json={"event_type": "delivered", "location": "Reception"},
        headers=h["staff"],
    ).json()
    assert [e["event_type"] for e in delivered["events"]] == ["dispatched", "delayed", "delivered"]
    order = client.get(f"{API}/orders/{order['id']}", headers=h["customer"]).json()
    assert order["status"] == "delivered"
    tracking = client.get(f"{API}/orders/{order['id']}/shipment", headers=h["customer"]).json()
    assert tracking["status"] == "delivered"

    # 6. The customer returns one mouse; staff inspect it as damaged
    ret = client.post(
        f"{API}/returns",
        json={
            "order_id": order["id"],
            "reason": "Scroll wheel broken",
            "items": [{"product_id": mou.id, "quantity": 1}],
        },
        headers=h["customer"],
    )
    assert ret.status_code == 201, ret.text
    inspected = client.post(
        f"{API}/returns/{ret.json()['id']}/inspect",
        json={"items": [{"product_id": mou.id, "condition": "damaged"}]},
        headers=h["staff"],
    ).json()
    assert inspected["status"] == "completed"
    assert inspected["items"][0]["bin"]["location_code"] == "WH01-ZR-R01-S01-B01"
    assert stock(client, w, mou) == {"on_hand": 8, "reserved": 0, "damaged": 1, "available": 7}
    order = client.get(f"{API}/orders/{order['id']}", headers=h["customer"]).json()
    assert order["status"] == "returned"
    assert [i["quantity_returned"] for i in order["items"]] == [0, 1]

    # The whole journey is in the history, and the movements explain all stock
    assert [entry["to_status"] for entry in order["history"]] == [
        "created",
        "confirmed",
        "inventory_reserved",
        "allocated",
        "picking",
        "picked",
        "packing",
        "packed",
        "shipped",
        "delayed",
        "delivered",
        "returned",
    ]
    for product in (lap, mou):
        on_hand, reserved, damaged = db_session.execute(
            select(
                func.sum(InventoryMovement.on_hand_delta),
                func.sum(InventoryMovement.reserved_delta),
                func.sum(InventoryMovement.damaged_delta),
            ).where(InventoryMovement.product_id == product.id)
        ).one()
        current = stock(client, w, product)
        assert (on_hand, reserved, damaged) == (
            current["on_hand"],
            current["reserved"],
            current["damaged"],
        )


# ============================================================================ permissions
def test_customers_see_only_their_own_orders(client: TestClient, world: dict):
    w, h = world, world["h"]
    mine = place_order(client, w, [(w["lap"], 1)])
    theirs = place_order(client, w, [(w["mou"], 1)], who="manager", customer=w["other_customer"])

    listed = client.get(f"{API}/orders", headers=h["customer"]).json()
    assert [o["order_number"] for o in listed["items"]] == [mine["order_number"]]
    assert client.get(f"{API}/orders/{theirs['id']}", headers=h["customer"]).status_code == 404
    assert (
        client.post(f"{API}/orders/{theirs['id']}/confirm", headers=h["customer"]).status_code
        == 404
    )
    everything = client.get(f"{API}/orders", headers=h["staff"]).json()
    assert everything["total"] == 2
    by_customer = client.get(
        f"{API}/orders", params={"customer_id": w["other_customer"].id}, headers=h["manager"]
    ).json()
    assert by_customer["total"] == 1


def test_who_may_place_and_change_orders(client: TestClient, world: dict):
    w, h = world, world["h"]
    body = {
        "customer_id": w["other_customer"].id,
        "items": [{"product_id": w["lap"].id, "quantity": 1}],
    }

    assert client.post(f"{API}/orders", json=body, headers=h["customer"]).status_code == 403
    assert client.post(f"{API}/orders", json=body, headers=h["staff"]).status_code == 403
    assert client.post(f"{API}/orders", json=body, headers=h["unlinked"]).status_code == 403
    assert client.get(f"{API}/orders", headers=h["unlinked"]).status_code == 403
    order = place_order(client, w, [(w["lap"], 1)])

    reason = {"reason": "Payment check"}
    assert (
        client.post(
            f"{API}/orders/{order['id']}/hold", json=reason, headers=h["customer"]
        ).status_code
        == 403
    )
    assert client.post(f"{API}/orders/{order['id']}/confirm", headers=h["staff"]).status_code == 403
    assert (
        client.post(
            f"{API}/orders/{order['id']}/hold", json=reason, headers=h["manager"]
        ).status_code
        == 200
    )
    released = client.post(f"{API}/orders/{order['id']}/release", headers=h["manager"]).json()
    assert released["status"] == "created"
    cancelled = client.post(
        f"{API}/orders/{order['id']}/cancel",
        json={"reason": "Changed my mind"},
        headers=h["customer"],
    )
    assert cancelled.json()["status"] == "cancelled"
    again = client.post(f"{API}/orders/{order['id']}/confirm", headers=h["manager"])
    assert again.status_code == 409


def test_fulfillment_is_for_warehouse_roles_only(client: TestClient, world: dict):
    h = world["h"]
    for url in (f"{API}/picking-tasks", f"{API}/packing-tasks"):
        assert client.get(url, headers=h["customer"]).status_code == 403
        assert client.get(url, headers=h["staff"]).status_code == 200
    assert client.post(f"{API}/shipments/check-delays", headers=h["staff"]).status_code == 403
    assert client.post(f"{API}/shipments/check-delays", headers=h["manager"]).json() == []
    carriers = client.get(f"{API}/carriers", headers=h["customer"]).json()
    assert [c["code"] for c in carriers] == ["DHL"]


def test_customer_records(client: TestClient, world: dict):
    h = world["h"]

    me = client.get(f"{API}/customers/me", headers=h["customer"]).json()
    assert me["code"] == "CUST-0001"
    assert client.get(f"{API}/customers/me", headers=h["staff"]).status_code == 404
    assert client.get(f"{API}/customers", headers=h["customer"]).status_code == 403
    assert client.get(f"{API}/customers", headers=h["staff"]).json()["total"] == 2

    created = client.post(
        f"{API}/customers",
        json={"name": "New GmbH", "city": "Ulm", "user_id": world["users"]["unlinked"].id},
        headers=h["manager"],
    )
    assert created.status_code == 201
    assert created.json()["code"] == "CUST-0003"  # generated
    assert (
        client.post(f"{API}/customers", json={"name": "X"}, headers=h["staff"]).status_code == 403
    )
    taken = client.post(
        f"{API}/customers",
        json={"name": "Dup", "user_id": world["users"]["customer"].id},
        headers=h["manager"],
    )
    assert taken.status_code == 409
    not_a_customer = client.post(
        f"{API}/customers",
        json={"name": "Staff Co", "user_id": world["users"]["staff"].id},
        headers=h["manager"],
    )
    assert not_a_customer.status_code == 422
    changed = client.patch(
        f"{API}/customers/{created.json()['id']}", json={"city": "Munich"}, headers=h["manager"]
    )
    assert changed.json()["city"] == "Munich"


def test_returns_and_shipments_are_scoped_to_the_customer(client: TestClient, world: dict):
    w, h = world, world["h"]
    receive(client, w, w["mou"], w["bins"]["a"], 5)
    order = place_order(client, w, [(w["mou"], 2)])
    client.post(f"{API}/orders/{order['id']}/confirm", headers=h["customer"])
    [task] = client.post(f"{API}/orders/{order['id']}/allocate", headers=h["staff"]).json()
    client.post(f"{API}/picking-tasks/{task['id']}/start", headers=h["staff"])
    client.post(
        f"{API}/picking-tasks/{task['id']}/complete",
        json={
            "bin_code": task["bin"]["location_code"],
            "product_code": "MOU-001",
            "quantity_picked": 2,
        },
        headers=h["staff"],
    )
    [packing] = client.get(f"{API}/packing-tasks", headers=h["staff"]).json()["items"]
    client.post(f"{API}/packing-tasks/{packing['id']}/start", headers=h["staff"])
    client.post(
        f"{API}/packing-tasks/{packing['id']}/complete",
        json={
            "items": [{"product_id": w["mou"].id, "quantity": 2}],
            "package_count": 1,
            "weight_kg": "1",
        },
        headers=h["staff"],
    )
    shipment = client.post(
        f"{API}/shipments",
        json={"order_id": order["id"], "carrier_id": w["carrier"].id},
        headers=h["staff"],
    ).json()
    client.post(
        f"{API}/shipments/{shipment['id']}/events",
        json={"event_type": "delivered"},
        headers=h["staff"],
    )
    ret = client.post(
        f"{API}/returns",
        json={
            "order_id": order["id"],
            "reason": "Not needed",
            "items": [{"product_id": w["mou"].id, "quantity": 1}],
        },
        headers=h["customer"],
    ).json()

    for url in (f"{API}/shipments", f"{API}/returns"):
        assert client.get(url, headers=h["customer"]).json()["total"] == 1
        assert client.get(url, headers=h["other"]).json()["total"] == 0
        assert client.get(url, headers=h["staff"]).json()["total"] == 1
    assert client.get(f"{API}/shipments/{shipment['id']}", headers=h["other"]).status_code == 404
    assert client.get(f"{API}/returns/{ret['id']}", headers=h["other"]).status_code == 404
    assert client.get(f"{API}/orders/{order['id']}/shipment", headers=h["other"]).status_code == 404
    # Others cannot open a return for this order either
    stolen = client.post(
        f"{API}/returns",
        json={
            "order_id": order["id"],
            "reason": "Mine now",
            "items": [{"product_id": w["mou"].id, "quantity": 1}],
        },
        headers=h["other"],
    )
    assert stolen.status_code == 404
