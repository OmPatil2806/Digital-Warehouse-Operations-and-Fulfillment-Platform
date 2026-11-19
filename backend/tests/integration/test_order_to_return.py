"""Scenario: a customer order from creation to delivery, and a return afterwards.

    receive stock -> order -> confirm (reserve) -> allocate (picking route) -> pick
    -> pack -> ship -> track -> deliver -> return -> inspect (restock / damaged)

Every step goes through the API with the role that does it, and the stock, the order
status, the customer's view and the audit trail are checked along the way.
"""

from fastapi.testclient import TestClient

from tests.integration.conftest import Warehouse, ok, stock

API = "/api/v1"


def receive(client: TestClient, w: Warehouse, product: int, quantity: int) -> None:
    ok(
        client.post(
            f"{API}/inventory/receive",
            json={"product_id": product, "bin_id": w.pick_bin, "quantity": quantity},
            headers=w.staff,
        ),
        201,
    )


def place_order(client: TestClient, w: Warehouse) -> dict:
    """2 laptops and 3 mice for the customer, confirmed (stock reserved)."""
    order = ok(
        client.post(
            f"{API}/orders",
            json={
                "customer_id": w.customer_id,
                "items": [
                    {"product_id": w.laptop, "quantity": 2},
                    {"product_id": w.mouse, "quantity": 3},
                ],
                "ship_to_name": "Chris Customer",
            },
            headers=w.manager,
        ),
        201,
    )
    return ok(client.post(f"{API}/orders/{order['id']}/confirm", headers=w.manager))


def pick_and_pack(client: TestClient, w: Warehouse, order_id: int) -> None:
    tasks = ok(client.post(f"{API}/orders/{order_id}/allocate", headers=w.manager))
    assert {t["product"]["sku"] for t in tasks} == {"LAP-001", "MOU-001"}
    for task in tasks:
        ok(client.post(f"{API}/picking-tasks/{task['id']}/start", headers=w.staff))
        ok(
            client.post(
                f"{API}/picking-tasks/{task['id']}/complete",
                json={
                    "bin_code": task["bin"]["location_code"],
                    "product_code": task["product"]["sku"],
                    "quantity_picked": task["quantity"],
                },
                headers=w.staff,
            )
        )
    packing = ok(client.get(f"{API}/packing-tasks", headers=w.staff))["items"]
    (task,) = [t for t in packing if t["order"]["id"] == order_id]
    ok(client.post(f"{API}/packing-tasks/{task['id']}/start", headers=w.staff))
    ok(
        client.post(
            f"{API}/packing-tasks/{task['id']}/complete",
            json={
                "items": [
                    {"product_id": w.laptop, "quantity": 2},
                    {"product_id": w.mouse, "quantity": 3},
                ],
                "package_count": 2,
                "weight_kg": "7.250",
            },
            headers=w.staff,
        )
    )


def status_of(client: TestClient, headers: dict[str, str], order_id: int) -> str:
    return ok(client.get(f"{API}/orders/{order_id}", headers=headers))["status"]


def test_order_from_creation_to_delivery_and_return(client: TestClient, warehouse: Warehouse):
    w = warehouse
    receive(client, w, w.laptop, 5)
    receive(client, w, w.mouse, 10)

    # Order and reservation
    order = place_order(client, w)
    order_id = order["id"]
    assert order["status"] == "inventory_reserved"
    assert stock(client, w.manager, w.laptop) == {
        "quantity_on_hand": 5,
        "quantity_reserved": 2,
        "quantity_available": 3,
    }

    # Picking and packing: the units leave the shelf when picked
    pick_and_pack(client, w, order_id)
    assert status_of(client, w.manager, order_id) == "packed"
    assert stock(client, w.manager, w.laptop)["quantity_on_hand"] == 3
    assert stock(client, w.manager, w.mouse)["quantity_reserved"] == 0

    # Shipping and tracking
    shipment = ok(
        client.post(
            f"{API}/shipments",
            json={"order_id": order_id, "carrier_id": w.carrier, "tracking_number": "DHL-12345"},
            headers=w.staff,
        ),
        201,
    )
    assert status_of(client, w.manager, order_id) == "shipped"
    for event in ("in_transit", "out_for_delivery", "delivered"):
        ok(
            client.post(
                f"{API}/shipments/{shipment['id']}/events",
                json={"event_type": event, "location": "Stuttgart"},
                headers=w.staff,
            ),
            201,
        )
    assert status_of(client, w.manager, order_id) == "delivered"

    # The customer sees their own order, delivered, but no other order
    mine = ok(client.get(f"{API}/orders", headers=w.customer))
    assert [o["id"] for o in mine["items"]] == [order_id]
    assert status_of(client, w.customer, order_id) == "delivered"

    # Return: one laptop back in good condition, one mouse damaged
    returned = ok(
        client.post(
            f"{API}/returns",
            json={
                "order_id": order_id,
                "reason": "Changed my mind",
                "items": [
                    {"product_id": w.laptop, "quantity": 1},
                    {"product_id": w.mouse, "quantity": 1},
                ],
            },
            headers=w.manager,
        ),
        201,
    )
    ok(
        client.post(
            f"{API}/returns/{returned['id']}/inspect",
            json={
                "items": [
                    {"product_id": w.laptop, "condition": "restock", "bin_id": w.returns_bin},
                    {"product_id": w.mouse, "condition": "damaged", "bin_id": w.returns_bin},
                ]
            },
            headers=w.staff,
        )
    )
    assert stock(client, w.manager, w.laptop)["quantity_available"] == 4  # restocked
    assert stock(client, w.manager, w.mouse)["quantity_available"] == 7  # damaged: not sellable

    # Every step left a trace in the stock history and the order timeline
    moves = ok(
        client.get(f"{API}/inventory/movements", params={"product_id": w.laptop}, headers=w.manager)
    )
    kinds = {m["movement_type"] for m in moves["items"]}
    assert {"receipt", "reservation", "pick", "return"} <= kinds, kinds
    timeline = ok(client.get(f"{API}/orders/{order_id}", headers=w.manager))["history"]
    assert [h["to_status"] for h in timeline][-1] in {"delivered", "returned", "partially_returned"}


def test_staff_and_customers_cannot_skip_their_role(client: TestClient, warehouse: Warehouse):
    """The same flow refuses actions outside each role."""
    w = warehouse
    receive(client, w, w.laptop, 5)
    receive(client, w, w.mouse, 10)
    order_id = place_order(client, w)["id"]
    # Staff run the floor but do not cancel orders; customers never allocate or ship.
    assert (
        client.post(
            f"{API}/orders/{order_id}/cancel", json={"reason": "Customer asked"}, headers=w.staff
        ).status_code
        == 403
    )
    assert client.post(f"{API}/orders/{order_id}/allocate", headers=w.customer).status_code == 403
    shipped = client.post(
        f"{API}/shipments", json={"order_id": order_id, "carrier_id": w.carrier}, headers=w.customer
    )
    assert shipped.status_code == 403
    # An order cannot be shipped before it is packed.
    early = client.post(
        f"{API}/shipments", json={"order_id": order_id, "carrier_id": w.carrier}, headers=w.staff
    )
    assert early.status_code in (409, 422), early.text


def test_unknown_orders_and_retrying_reservations(client: TestClient, warehouse: Warehouse):
    w = warehouse
    assert client.get(f"{API}/orders/999", headers=w.manager).status_code == 404
    assert client.post(f"{API}/orders/999/confirm", headers=w.manager).status_code == 404
    receive(client, w, w.laptop, 1)
    receive(client, w, w.mouse, 3)
    order_id = place_order(client, w)["id"]  # 2 laptops, only 1 in stock
    assert status_of(client, w.manager, order_id) == "partially_allocated"
    # Retrying without new stock changes nothing; with it, the order is fully reserved.
    retried = ok(client.post(f"{API}/orders/{order_id}/reserve", headers=w.manager))
    assert retried["status"] == "partially_allocated"
    receive(client, w, w.laptop, 1)  # a receipt fills waiting orders by itself
    assert status_of(client, w.manager, order_id) == "inventory_reserved"
    # A fully reserved order is not waiting for stock any more.
    again = client.post(f"{API}/orders/{order_id}/reserve", headers=w.manager)
    assert again.status_code == 409 and "wait for stock" in again.json()["detail"]
