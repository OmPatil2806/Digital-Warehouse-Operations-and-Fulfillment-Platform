"""The search filters of the work lists, on data made by the real order flow.

Two customers order; one order is delivered and partly returned, the other only
confirmed. The lists the web app filters (orders, customers, picking queue, shipments,
returns) must return exactly the matching rows, and customers only their own.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.factories import create_customer
from tests.integration.conftest import Warehouse, ok
from tests.integration.test_order_to_return import pick_and_pack, place_order, receive

API = "/api/v1"


def ids(client: TestClient, path: str, headers: dict[str, str], **params: object) -> list[int]:
    return [
        row["id"]
        for row in ok(client.get(f"{API}/{path}", params=params, headers=headers))["items"]
    ]


def test_filters_return_exactly_the_matching_rows(
    client: TestClient, db_session: Session, warehouse: Warehouse
):
    w = warehouse
    receive(client, w, w.laptop, 10)
    receive(client, w, w.mouse, 20)
    other = create_customer(db_session, "CUST-0002", name="Zeta Retail", email="buy@zeta.example")

    # Order A: Chris's, delivered and partly returned. Order B: Zeta's, only confirmed.
    a = place_order(client, w)["id"]
    pick_and_pack(client, w, a)
    shipment = ok(
        client.post(
            f"{API}/shipments",
            json={
                "order_id": a,
                "carrier_id": w.carrier,
                "tracking_number": "TRACK-A1",
            },
            headers=w.staff,
        ),
        201,
    )
    ok(
        client.post(
            f"{API}/shipments/{shipment['id']}/events",
            json={"event_type": "delivered"},
            headers=w.staff,
        ),
        201,
    )
    returned = ok(
        client.post(
            f"{API}/returns",
            json={
                "order_id": a,
                "reason": "Too many",
                "items": [{"product_id": w.mouse, "quantity": 1}],
            },
            headers=w.manager,
        ),
        201,
    )
    b = ok(
        client.post(
            f"{API}/orders",
            json={
                "customer_id": other.id,
                "items": [{"product_id": w.laptop, "quantity": 1}],
            },
            headers=w.manager,
        ),
        201,
    )["id"]
    ok(client.post(f"{API}/orders/{b}/confirm", headers=w.manager))
    number_b = ok(client.get(f"{API}/orders/{b}", headers=w.manager))["order_number"]

    # Orders: by number, by customer name or code, by status, by customer
    assert ids(client, "orders", w.manager, q=number_b) == [b]
    assert ids(client, "orders", w.manager, q="zeta") == [b]
    assert ids(client, "orders", w.manager, q="CUST-0001") == [a]
    assert ids(client, "orders", w.manager, status="delivered") == [a]
    assert ids(client, "orders", w.manager, customer_id=other.id) == [b]
    assert ids(client, "orders", w.manager, q="100%_") == []  # wildcards are plain text
    # Any case, any part of the number, the digits alone, or text no number can contain.
    number_a = ok(client.get(f"{API}/orders/{a}", headers=w.manager))["order_number"]
    assert ids(client, "orders", w.manager, q=number_b.lower()) == [b]
    assert ids(client, "orders", w.manager, q=number_b[:7].lower()) == [b, a]  # "so-2026"
    assert ids(client, "orders", w.manager, q=number_a[-6:]) == [a]  # "000001"
    assert ids(client, "orders", w.manager, q=number_a[3:]) == [a]  # "2026-000001"
    assert ids(client, "orders", w.manager, q="retail") == [b]  # customer name only
    # A customer's filter cannot widen their view.
    assert ids(client, "orders", w.customer, customer_id=other.id) == [a]

    # Customers: by name, code or e-mail, and active or not
    assert ids(client, "customers", w.manager, q="zeta.example") == [other.id]
    ok(client.patch(f"{API}/customers/{other.id}", json={"is_active": False}, headers=w.manager))
    assert ids(client, "customers", w.manager, is_active=False) == [other.id]
    assert ids(client, "customers", w.manager, is_active=True) == [w.customer_id]

    # Picking queue: order B's task, by order and by who started it
    ok(client.post(f"{API}/orders/{b}/allocate", headers=w.manager))
    (task,) = ok(client.get(f"{API}/picking-tasks", params={"order_id": b}, headers=w.staff))[
        "items"
    ]
    assert ids(client, "picking-tasks", w.staff, mine=True) == []
    ok(client.post(f"{API}/picking-tasks/{task['id']}/start", headers=w.staff))
    assert ids(client, "picking-tasks", w.staff, mine=True) == [task["id"]]
    assert ids(client, "picking-tasks", w.manager, mine=True) == []
    assert len(ids(client, "picking-tasks", w.staff, status="completed", order_id=a)) == 2

    # Shipments: by tracking number or order number, by status; customers see their own
    assert ids(client, "shipments", w.staff, q="track-a") == [shipment["id"]]
    assert ids(client, "shipments", w.staff, q=number_a.lower()) == [shipment["id"]]
    assert ids(client, "shipments", w.staff, q=number_b) == []  # B has not shipped
    assert ids(client, "shipments", w.staff, status="delivered") == [shipment["id"]]
    assert ids(client, "shipments", w.staff, status="dispatched") == []
    assert ids(client, "shipments", w.customer) == [shipment["id"]]

    # Returns: by order and status; customers see their own only
    assert ids(client, "returns", w.manager, order_id=a) == [returned["id"]]
    assert ids(client, "returns", w.manager, order_id=b) == []
    assert ids(client, "returns", w.manager, status=returned["status"]) == [returned["id"]]
    assert ids(client, "returns", w.customer) == [returned["id"]]
