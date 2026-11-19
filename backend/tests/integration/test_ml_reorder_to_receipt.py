"""Scenario: an ML stockout warning becomes stock on the shelf.

    scoring run (offline) -> dashboard and ML insights show the warning
    -> manager approves -> draft purchase order -> ordered -> received -> stock up

The scoring step runs offline (scripts/score_models.py), so the recommendation is
written straight into its table here; everything after it goes through the API.
"""

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.ml import MetricSplit, ModelMetric, ModelStatus, ModelVersion, UseCase
from app.models.ml_results import ReorderRecommendation
from app.models.user import RoleName
from tests.factories import auth_headers, create_user
from tests.integration.conftest import Warehouse, ok, stock

API = "/api/v1"
AS_OF = date(2026, 11, 10)


def score_reorder(db: Session, w: Warehouse, warehouse_id: int) -> None:
    """What the scoring step stores: the laptop will likely run out within 14 days."""
    model = ModelVersion(
        use_case=UseCase.REORDER,
        model_name="lstm",
        version="v1",
        dataset_version="test",
        features=[],
        hyperparameters={},
        artifact_path="artifacts/reorder.keras",
        is_baseline=False,
        status=ModelStatus.SELECTED,
        trained_at=datetime(2026, 11, 1, tzinfo=UTC),
        metrics=[ModelMetric(split=MetricSplit.TEST, name="pr_auc", value=0.33)],
    )
    db.add(model)
    db.flush()
    db.add(
        ReorderRecommendation(
            product_id=w.laptop,
            warehouse_id=warehouse_id,
            probability=0.81,
            priority="high",
            reorder_date=AS_OF,
            quantity=12,
            reasons=["Low available stock", "Demand rising"],
            model_version_id=model.id,
            scored_at=datetime(2026, 11, 10, 22, tzinfo=UTC),
            as_of=AS_OF,
        )
    )
    db.commit()


def test_approved_ml_reorder_ends_as_received_stock(
    client: TestClient, db_session: Session, warehouse: Warehouse
):
    w = warehouse
    (warehouse_row,) = ok(client.get(f"{API}/warehouses", headers=w.manager))
    # The laptop has a supplier who sells at least 20 at a time.
    supplier = ok(
        client.post(
            f"{API}/suppliers",
            json={"code": "SUP-200", "name": "Laptop Wholesale"},
            headers=w.manager,
        ),
        201,
    )
    ok(
        client.post(
            f"{API}/suppliers/{supplier['id']}/products",
            json={"product_id": w.laptop, "unit_cost": "52.00", "min_order_qty": 20},
            headers=w.manager,
        ),
        201,
    )
    ok(
        client.patch(
            f"{API}/products/{w.laptop}",
            json={"default_supplier_id": supplier["id"]},
            headers=w.manager,
        )
    )
    score_reorder(db_session, w, warehouse_row["id"])

    # The warning shows on the dashboard and in ML insights.
    summary = ok(client.get(f"{API}/ml/summary", headers=w.manager))
    assert (summary["stockouts_pending"], summary["stockouts_high"]) == (1, 1)
    (rec,) = ok(client.get(f"{API}/ml/reorder-recommendations", headers=w.staff))["items"]
    assert rec["product"]["sku"] == "LAP-001" and rec["reasons"][0] == "Low available stock"

    # Staff can read it but not decide; the manager approves.
    approve = f"{API}/ml/reorder-recommendations/{rec['id']}/approve"
    assert client.post(approve, headers=w.staff).status_code == 403
    decided = ok(client.post(approve, json={"note": "Order before the peak"}, headers=w.manager))
    assert decided["status"] == "approved" and decided["purchase_order_id"]
    assert client.post(approve, headers=w.manager).status_code == 409  # decided once only

    # The draft purchase order: the supplier's minimum, the supplier's price, and a note.
    po = ok(client.get(f"{API}/purchase-orders/{decided['purchase_order_id']}", headers=w.manager))
    assert po["status"] == "draft" and po["supplier"]["code"] == "SUP-200"
    (line,) = po["items"]
    assert (line["quantity"], float(line["unit_cost"])) == (20, 52.0)
    assert f"#{rec['id']}" in po["notes"]
    summary = ok(client.get(f"{API}/ml/summary", headers=w.manager))
    assert summary["stockouts_pending"] == 0

    # The manager sends it; the goods arrive and go on the shelf.
    ok(client.post(f"{API}/purchase-orders/{po['id']}/order", headers=w.manager))
    received = ok(
        client.post(
            f"{API}/purchase-orders/{po['id']}/receive",
            json={"items": [{"product_id": w.laptop, "quantity": 20, "bin_id": w.pick_bin}]},
            headers=w.manager,
        )
    )
    assert received["status"] == "received"
    assert stock(client, w.manager, w.laptop)["quantity_available"] == 20

    # The decision is in the audit log (read by an admin), with who made it.
    admin = auth_headers(create_user(db_session, "ada@example.com", roles=(RoleName.ADMIN,)))
    assert client.get(f"{API}/audit-logs", headers=w.manager).status_code == 403
    logs = ok(
        client.get(f"{API}/audit-logs", params={"action": "ml.reorder.approve"}, headers=admin)
    )["items"]
    assert len(logs) == 1 and logs[0]["actor_email"] == "maya@example.com"
