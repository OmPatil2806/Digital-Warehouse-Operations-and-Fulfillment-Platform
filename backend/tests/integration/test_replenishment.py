"""Scenario: stock runs low, an order waits for stock, and a supplier delivery fixes both.

    minimum stock -> low-stock alert -> order larger than the stock (backordered)
    -> purchase order (draft -> ordered) -> partial delivery -> full delivery
    -> backorder filled, alert resolved automatically

All through the API: the manager plans and buys, staff receive the goods.
"""

from fastapi.testclient import TestClient

from tests.integration.conftest import Warehouse, ok, stock

API = "/api/v1"


def low_stock_alerts(client: TestClient, w: Warehouse) -> list[dict]:
    alerts = ok(client.get(f"{API}/alerts", headers=w.manager))["items"]
    return [
        a
        for a in alerts
        if a["alert_type"] == "low_stock" and a["status"] in ("open", "acknowledged")
    ]


def test_low_stock_purchase_order_and_backorder(client: TestClient, warehouse: Warehouse):
    w = warehouse
    # The manager sets a minimum stock; 4 laptops are fewer than that.
    ok(client.patch(f"{API}/products/{w.laptop}", json={"min_stock": 10}, headers=w.manager))
    ok(
        client.post(
            f"{API}/inventory/receive",
            json={"product_id": w.laptop, "bin_id": w.pick_bin, "quantity": 4},
            headers=w.staff,
        ),
        201,
    )
    (alert,) = low_stock_alerts(client, w)
    assert alert["severity"] == "warning"
    ok(client.post(f"{API}/alerts/{alert['id']}/acknowledge", headers=w.manager))

    # A customer orders 6: 4 are reserved, 2 wait for stock.
    order = ok(
        client.post(
            f"{API}/orders",
            json={"customer_id": w.customer_id, "items": [{"product_id": w.laptop, "quantity": 6}]},
            headers=w.manager,
        ),
        201,
    )
    order = ok(client.post(f"{API}/orders/{order['id']}/confirm", headers=w.manager))
    assert order["status"] == "partially_allocated"
    assert stock(client, w.manager, w.laptop)["quantity_available"] == 0
    (alert,) = low_stock_alerts(client, w)
    assert alert["severity"] == "critical"  # nothing left to sell

    # The manager buys 20 from a supplier.
    supplier = ok(
        client.post(
            f"{API}/suppliers",
            json={"code": "SUP-100", "name": "Laptop Wholesale", "lead_time_days": 5},
            headers=w.manager,
        ),
        201,
    )
    ok(
        client.post(
            f"{API}/suppliers/{supplier['id']}/products",
            json={"product_id": w.laptop, "unit_cost": "55.00", "min_order_qty": 10},
            headers=w.manager,
        ),
        201,
    )
    (warehouse_row,) = ok(client.get(f"{API}/warehouses", headers=w.manager))
    warehouse_id = warehouse_row["id"]
    po = ok(
        client.post(
            f"{API}/purchase-orders",
            json={
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse_id,
                "items": [{"product_id": w.laptop, "quantity": 20}],
            },
            headers=w.manager,
        ),
        201,
    )
    assert po["status"] == "draft"
    assert float(po["items"][0]["unit_cost"]) == 55.0  # the supplier's price
    assert ok(client.post(f"{API}/purchase-orders/{po['id']}/order", headers=w.manager))[
        "status"
    ] == ("ordered")

    # Staff may not buy, and nobody can receive more than was ordered.
    assert (
        client.post(
            f"{API}/purchase-orders",
            json={
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse_id,
                "items": [{"product_id": w.laptop, "quantity": 1}],
            },
            headers=w.staff,
        ).status_code
        == 403
    )
    too_many = client.post(
        f"{API}/purchase-orders/{po['id']}/receive",
        json={"items": [{"product_id": w.laptop, "quantity": 21, "bin_id": w.pick_bin}]},
        headers=w.manager,
    )
    assert too_many.status_code in (409, 422), too_many.text

    # First delivery of 5: the backorder (2) is filled first.
    partial = ok(
        client.post(
            f"{API}/purchase-orders/{po['id']}/receive",
            json={"items": [{"product_id": w.laptop, "quantity": 5, "bin_id": w.pick_bin}]},
            headers=w.manager,
        )
    )
    assert partial["status"] == "partially_received"
    assert ok(client.get(f"{API}/orders/{order['id']}", headers=w.manager))["status"] == (
        "inventory_reserved"
    )
    assert stock(client, w.manager, w.laptop) == {
        "quantity_on_hand": 9,
        "quantity_reserved": 6,
        "quantity_available": 3,
    }
    assert len(low_stock_alerts(client, w)) == 1  # 3 available: still below 10

    # The rest arrives: 18 available, above the minimum, so the alert resolves itself.
    done = ok(
        client.post(
            f"{API}/purchase-orders/{po['id']}/receive",
            json={"items": [{"product_id": w.laptop, "quantity": 15, "bin_id": w.pick_bin}]},
            headers=w.manager,
        )
    )
    assert done["status"] == "received"
    assert stock(client, w.manager, w.laptop)["quantity_available"] == 18
    assert low_stock_alerts(client, w) == []

    # The receipts carry the purchase-order number in the stock history.
    moves = ok(
        client.get(f"{API}/inventory/movements", params={"product_id": w.laptop}, headers=w.manager)
    )["items"]
    assert sum(po["po_number"] in (m["reason"] or "") for m in moves) == 2
