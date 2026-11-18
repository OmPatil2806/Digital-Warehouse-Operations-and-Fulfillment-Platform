"""Tests for the ML prediction endpoints (/api/v1/ml)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.catalog import SupplierProduct
from app.models.ml import MetricSplit, ModelMetric, ModelStatus, ModelVersion, UseCase
from app.models.ml_results import (
    DelayPrediction,
    DemandForecast,
    MovementClassification,
    ProductRecommendation,
    ReorderRecommendation,
    SlottingRecommendation,
)
from app.models.order import Order
from app.models.purchase import PurchaseOrder
from app.models.shipment import Shipment
from app.models.user import RoleName
from tests.factories import (
    auth_headers,
    create_bin,
    create_carrier,
    create_category,
    create_customer,
    create_product,
    create_supplier,
    user_with_role,
)

OLD = datetime(2026, 11, 1, 12, tzinfo=UTC)
NEW = datetime(2026, 11, 10, 12, tzinfo=UTC)
AS_OF = date(2026, 11, 10)


@dataclass
class World:
    products: list
    warehouse_id: int
    bins: list
    order: Order
    models: dict


def model(db: Session, use_case: UseCase, name: str, *, baseline: bool = False) -> ModelVersion:
    row = ModelVersion(
        use_case=use_case,
        model_name=name,
        version="v1",
        dataset_version="orders500-to2026-11-10-abc",
        features=[],
        hyperparameters={},
        artifact_path=None if baseline else f"artifacts/{name}.keras",
        is_baseline=baseline,
        status=ModelStatus.SELECTED,
        trained_at=OLD,
        metrics=[ModelMetric(split=MetricSplit.TEST, name="pr_auc", value=0.33)],
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def world(db_session: Session) -> World:
    db = db_session
    category = create_category(db)
    products = [
        create_product(db, category, sku=f"SKU-{i}", name=f"Product {i}") for i in range(1, 4)
    ]
    near = create_bin(db, "WH01-ZA-R01-S01-B01")
    far = create_bin(db, "WH01-ZA-R01-S01-B02")
    warehouse_id = near.shelf.rack.zone.warehouse_id
    customer = create_customer(db)
    order = Order(
        order_number="SO-2026-000001",
        customer_id=customer.id,
        warehouse_id=warehouse_id,
        status="shipped",
        priority="normal",
        ship_to_name="Someone",
        subtotal=Decimal("10.00"),
    )
    db.add(order)
    db.flush()
    shipment = Shipment(
        order_id=order.id,
        carrier_id=create_carrier(db).id,
        tracking_number="DHL123",
        status="dispatched",
        package_count=1,
        weight_kg=Decimal("1.000"),
        shipped_at=NEW,
        expected_delivery_date=AS_OF + timedelta(days=2),
    )
    db.add(shipment)
    db.flush()
    models = {
        UseCase.DEMAND: model(db, UseCase.DEMAND, "lstm"),
        UseCase.REORDER: model(db, UseCase.REORDER, "lstm"),
        UseCase.MOVEMENT: model(db, UseCase.MOVEMENT, "abc", baseline=True),
        UseCase.SLOTTING: model(db, UseCase.SLOTTING, "dense_suitability"),
        UseCase.DELAY: model(db, UseCase.DELAY, "lstm_events"),
        UseCase.RECOMMENDATION: model(
            db, UseCase.RECOMMENDATION, "frequently_bought_together", baseline=True
        ),
    }
    p1, p2, p3 = products

    def stamp(use_case: UseCase, when: datetime = NEW) -> dict:
        return {"model_version_id": models[use_case].id, "scored_at": when, "as_of": AS_OF}

    rows = []
    for day in range(1, 31):
        rows.append(
            DemandForecast(
                product_id=p1.id,
                day=AS_OF + timedelta(days=day),
                expected_units=2.0,
                low_units=1.0,
                high_units=4.0,
                **stamp(UseCase.DEMAND),
            )
        )
    rows.append(  # an older run must not show
        DemandForecast(
            product_id=p1.id,
            day=AS_OF,
            expected_units=99.0,
            low_units=0.0,
            high_units=99.0,
            **stamp(UseCase.DEMAND, OLD),
        )
    )
    for product, probability, priority in ((p1, 0.8, "high"), (p2, 0.3, "medium")):
        rows.append(
            ReorderRecommendation(
                product_id=product.id,
                warehouse_id=warehouse_id,
                probability=probability,
                priority=priority,
                reorder_date=AS_OF,
                quantity=12,
                reasons=["Low available stock"],
                **stamp(UseCase.REORDER),
            )
        )
    rows.append(
        ReorderRecommendation(
            product_id=p3.id,
            warehouse_id=warehouse_id,
            probability=0.9,
            priority="high",
            reorder_date=AS_OF,
            quantity=5,
            reasons=[],
            **stamp(UseCase.REORDER, OLD),
        )
    )
    for product, cls, picks in ((p1, "fast", 3.0), (p2, "medium", 1.0), (p3, "slow", 0.0)):
        rows.append(
            MovementClassification(
                product_id=product.id,
                movement_class=cls,
                picks_per_day=picks,
                **stamp(UseCase.MOVEMENT),
            )
        )
    rows.append(
        SlottingRecommendation(
            product_id=p1.id,
            warehouse_id=warehouse_id,
            current_bin_id=far.id,
            recommended_bin_id=near.id,
            current_seconds_per_day=100.0,
            recommended_seconds_per_day=60.0,
            **stamp(UseCase.SLOTTING),
        )
    )
    rows.append(
        SlottingRecommendation(
            product_id=p2.id,
            warehouse_id=warehouse_id,
            current_bin_id=None,
            recommended_bin_id=near.id,
            current_seconds_per_day=None,
            recommended_seconds_per_day=10.0,
            **stamp(UseCase.SLOTTING),
        )
    )
    rows.append(
        DelayPrediction(
            order_id=order.id,
            shipment_id=shipment.id,
            probability=0.62,
            risk_level="high",
            reasons=["Peak season"],
            **stamp(UseCase.DELAY),
        )
    )
    for rank, other in enumerate((p2, p3), start=1):
        rows.append(
            ProductRecommendation(
                product_id=p1.id,
                recommended_product_id=other.id,
                rank=rank,
                score=10.0 - rank,
                **stamp(UseCase.RECOMMENDATION),
            )
        )
    p3.is_active = False
    supplier = create_supplier(db)
    p1.default_supplier_id = supplier.id  # p2 has no supplier: approving it is refused
    db.add(
        SupplierProduct(
            supplier_id=supplier.id,
            product_id=p1.id,
            unit_cost=Decimal("4.50"),
            min_order_qty=20,
            is_preferred=True,
        )
    )
    db.add_all(rows)
    db.commit()
    return World(products, warehouse_id, [near, far], order, models)


def as_(db: Session, role: RoleName) -> dict[str, str]:
    return auth_headers(user_with_role(db, role))


# ------------------------------------------------------------------------ access
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/ml/models",
        "/api/v1/ml/demand-forecasts/1",
        "/api/v1/ml/reorder-recommendations",
        "/api/v1/ml/movement-classifications",
        "/api/v1/ml/slotting-recommendations",
        "/api/v1/ml/delay-risks",
    ],
)
def test_customers_cannot_see_warehouse_predictions(
    client: TestClient, db_session: Session, path: str
) -> None:
    assert client.get(path, headers=as_(db_session, RoleName.CUSTOMER)).status_code == 403
    assert client.get(path).status_code == 401


def test_staff_can_read_but_not_decide(
    client: TestClient, db_session: Session, world: World
) -> None:
    staff = as_(db_session, RoleName.STAFF)
    page = client.get("/api/v1/ml/reorder-recommendations", headers=staff).json()
    first = page["items"][0]["id"]
    for path in (
        f"/api/v1/ml/reorder-recommendations/{first}/approve",
        f"/api/v1/ml/reorder-recommendations/{first}/reject",
    ):
        assert client.post(path, headers=staff).status_code == 403


# ------------------------------------------------------------------------- reads
def test_models(client: TestClient, db_session: Session, world: World) -> None:
    body = client.get("/api/v1/ml/models", headers=as_(db_session, RoleName.STAFF)).json()
    by_case = {m["use_case"]: m for m in body}
    assert set(by_case) == {u.value for u in UseCase}
    demand = by_case["demand_forecasting"]
    assert demand["model_name"] == "lstm" and demand["predictions"] == 30
    assert demand["test_metrics"] == {"pr_auc": 0.33} and demand["as_of"] == "2026-11-10"
    assert by_case["movement_classification"]["is_baseline"] is True


def test_demand_forecast_uses_the_latest_run(
    client: TestClient, db_session: Session, world: World
) -> None:
    headers = as_(db_session, RoleName.STAFF)
    p1, p2, _ = world.products
    body = client.get(f"/api/v1/ml/demand-forecasts/{p1.id}", headers=headers).json()
    assert body["product"]["sku"] == "SKU-1" and len(body["days"]) == 30
    assert body["days"][0]["day"] == "2026-11-11" and body["scoring"]["model_name"] == "lstm"
    assert [
        (t["days"], t["expected_units"], t["low_units"], t["high_units"]) for t in body["totals"]
    ] == [(7, 14, 7, 28), (14, 28, 14, 56), (30, 60, 30, 120)]
    empty = client.get(f"/api/v1/ml/demand-forecasts/{p2.id}", headers=headers).json()
    assert empty["days"] == [] and empty["totals"] == [] and empty["scoring"] is None
    assert client.get("/api/v1/ml/demand-forecasts/999", headers=headers).status_code == 404


def test_reorder_recommendations_filters(
    client: TestClient, db_session: Session, world: World
) -> None:
    headers = as_(db_session, RoleName.STAFF)
    body = client.get("/api/v1/ml/reorder-recommendations", headers=headers).json()
    assert body["total"] == 2  # the older run is not shown
    assert [i["probability"] for i in body["items"]] == [0.8, 0.3]  # highest risk first
    item = body["items"][0]
    assert item["warehouse_code"] == "WH01" and item["reasons"] == ["Low available stock"]
    assert item["status"] == "pending" and item["purchase_order_id"] is None
    high = client.get("/api/v1/ml/reorder-recommendations?priority=high", headers=headers).json()
    assert high["total"] == 1
    paged = client.get("/api/v1/ml/reorder-recommendations?limit=1&offset=1", headers=headers)
    assert paged.json()["items"][0]["probability"] == 0.3


def test_movement(client: TestClient, db_session: Session, world: World) -> None:
    headers = as_(db_session, RoleName.STAFF)
    p1, _, p3 = world.products
    one = client.get(f"/api/v1/ml/movement-classification/{p1.id}", headers=headers).json()
    assert one["movement_class"] == "fast" and one["picks_per_day"] == 3.0
    summary = client.get("/api/v1/ml/movement-classifications/summary", headers=headers).json()
    assert summary["counts"] == {"fast": 1, "medium": 1, "slow": 1}
    assert summary["pick_share"]["fast"] == pytest.approx(0.75)
    assert summary["scoring"]["is_baseline"] is True
    slow = client.get("/api/v1/ml/movement-classifications?movement_class=slow", headers=headers)
    assert [i["product"]["id"] for i in slow.json()["items"]] == [p3.id]


def test_slotting_recommendations(client: TestClient, db_session: Session, world: World) -> None:
    body = client.get(
        "/api/v1/ml/slotting-recommendations", headers=as_(db_session, RoleName.STAFF)
    ).json()
    assert body["total"] == 2
    first, second = body["items"]  # biggest saving first, new locations last
    assert first["seconds_saved_per_day"] == 40.0
    assert first["current_bin"]["location_code"] == "WH01-ZA-R01-S01-B02"
    assert first["recommended_bin"]["location_code"] == "WH01-ZA-R01-S01-B01"
    assert first["recommended_bin"]["level"] == 1
    assert second["current_bin"] is None and second["seconds_saved_per_day"] is None


def test_delay_risk(client: TestClient, db_session: Session, world: World) -> None:
    headers = as_(db_session, RoleName.STAFF)
    body = client.get(f"/api/v1/ml/delay-risk/{world.order.id}", headers=headers).json()
    prediction = body["prediction"]
    assert prediction["order_number"] == "SO-2026-000001" and prediction["risk_level"] == "high"
    assert prediction["reasons"] == ["Peak season"]
    listing = client.get("/api/v1/ml/delay-risks?risk_level=high", headers=headers).json()
    assert listing["total"] == 1
    assert client.get("/api/v1/ml/delay-risk/999", headers=headers).status_code == 404


def test_delay_risk_is_null_without_a_prediction(
    client: TestClient, db_session: Session, world: World
) -> None:
    db_session.query(DelayPrediction).delete()
    db_session.commit()
    body = client.get(
        f"/api/v1/ml/delay-risk/{world.order.id}", headers=as_(db_session, RoleName.STAFF)
    ).json()
    assert body == {"order_id": world.order.id, "prediction": None}


def test_product_recommendations_for_everyone(
    client: TestClient, db_session: Session, world: World
) -> None:
    p1, p2, p3 = world.products
    staff = client.get(
        f"/api/v1/ml/product-recommendations/{p1.id}", headers=as_(db_session, RoleName.STAFF)
    ).json()
    assert [i["product"]["id"] for i in staff["items"]] == [p2.id, p3.id]
    customer = client.get(
        f"/api/v1/ml/product-recommendations/{p1.id}", headers=as_(db_session, RoleName.CUSTOMER)
    ).json()
    assert [i["product"]["id"] for i in customer["items"]] == [p2.id]  # inactive left out
    assert customer["scoring"]["model_name"] == "frequently_bought_together"


def test_nothing_scored_yet(client: TestClient, db_session: Session) -> None:
    headers = as_(db_session, RoleName.MANAGER)
    assert client.get("/api/v1/ml/models", headers=headers).json() == []
    body = client.get("/api/v1/ml/reorder-recommendations", headers=headers).json()
    assert body["items"] == [] and body["total"] == 0
    summary = client.get("/api/v1/ml/movement-classifications/summary", headers=headers).json()
    assert summary["scoring"] is None and summary["counts"]["fast"] == 0


# --------------------------------------------------------------------- decisions
@pytest.mark.parametrize("kind", ["reorder", "slotting"])
def test_approve_and_reject_are_audited(
    client: TestClient, db_session: Session, world: World, kind: str
) -> None:
    manager = user_with_role(db_session, RoleName.MANAGER)
    headers = auth_headers(manager)
    base = f"/api/v1/ml/{kind}-recommendations"
    first, second = (i["id"] for i in client.get(base, headers=headers).json()["items"])

    approved = client.post(f"{base}/{first}/approve", headers=headers, json={"note": "Looks right"})
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "approved" and body["decided_by_id"] == manager.id
    assert body["decision_note"] == "Looks right" and body["decided_at"]
    rejected = client.post(f"{base}/{second}/reject", headers=headers)
    assert rejected.json()["status"] == "rejected" and rejected.json()["decision_note"] is None

    again = client.post(f"{base}/{first}/reject", headers=headers)
    assert again.status_code == 409 and "already approved" in again.json()["detail"]
    assert client.post(f"{base}/9999/approve", headers=headers).status_code == 404
    pending = client.get(f"{base}?status=pending", headers=headers).json()
    assert pending["total"] == 0

    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.action.like(f"ml.{kind}.%")).order_by(AuditLog.id)
    ).all()
    assert [a.action for a in audit] == [f"ml.{kind}.approve", f"ml.{kind}.reject"]
    assert audit[0].actor_id == manager.id and audit[0].entity_id == first
    assert audit[0].changes == {"status": {"old": "pending", "new": "approved"}}


def test_note_is_limited(client: TestClient, db_session: Session, world: World) -> None:
    headers = as_(db_session, RoleName.MANAGER)
    first = client.get("/api/v1/ml/reorder-recommendations", headers=headers).json()["items"][0]
    response = client.post(
        f"/api/v1/ml/reorder-recommendations/{first['id']}/approve",
        headers=headers,
        json={"note": "x" * 501},
    )
    assert response.status_code == 422


# ------------------------------------------------------------- reorder -> PO
def test_approving_a_reorder_drafts_a_purchase_order(
    client: TestClient, db_session: Session, world: World
) -> None:
    manager = user_with_role(db_session, RoleName.MANAGER)
    headers = auth_headers(manager)
    first = client.get("/api/v1/ml/reorder-recommendations", headers=headers).json()["items"][0]
    body = client.post(
        f"/api/v1/ml/reorder-recommendations/{first['id']}/approve", headers=headers
    ).json()
    po = db_session.get(PurchaseOrder, body["purchase_order_id"])
    assert po is not None and po.status == "draft" and po.created_by_id == manager.id
    assert po.warehouse_id == world.warehouse_id and po.supplier.code == "SUP-001"
    assert [(i.product_id, i.quantity, i.unit_cost) for i in po.items] == [
        (world.products[0].id, 20, Decimal("4.50"))  # 12 recommended, supplier minimum 20
    ]
    assert f"recommendation #{first['id']}" in po.notes and "risk 80%" in po.notes
    actions = db_session.scalars(select(AuditLog.action).order_by(AuditLog.id)).all()
    assert actions[-2:] == ["purchase_order.create", "ml.reorder.approve"]


def test_no_supplier_no_approval(client: TestClient, db_session: Session, world: World) -> None:
    headers = as_(db_session, RoleName.MANAGER)
    second = client.get("/api/v1/ml/reorder-recommendations", headers=headers).json()["items"][1]
    response = client.post(
        f"/api/v1/ml/reorder-recommendations/{second['id']}/approve", headers=headers
    )
    assert response.status_code == 422 and "no supplier" in response.json()["detail"]
    again = client.get("/api/v1/ml/reorder-recommendations", headers=headers).json()["items"][1]
    assert again["status"] == "pending" and again["purchase_order_id"] is None
    assert db_session.scalars(select(PurchaseOrder)).all() == []


def test_rejecting_drafts_nothing(client: TestClient, db_session: Session, world: World) -> None:
    headers = as_(db_session, RoleName.MANAGER)
    first = client.get("/api/v1/ml/reorder-recommendations", headers=headers).json()["items"][0]
    body = client.post(
        f"/api/v1/ml/reorder-recommendations/{first['id']}/reject", headers=headers
    ).json()
    assert body["purchase_order_id"] is None
    assert db_session.scalars(select(PurchaseOrder)).all() == []


# ------------------------------------------------------------------ summary
def test_summary(client: TestClient, db_session: Session, world: World) -> None:
    headers = as_(db_session, RoleName.STAFF)
    body = client.get("/api/v1/ml/summary", headers=headers).json()
    assert body == {
        "as_of": "2026-11-10",
        "stockouts_high": 1,
        "stockouts_pending": 2,  # the older run does not count
        "orders_high_risk": 1,
        "orders_at_risk": 1,
        "orders_on_the_way": 1,
        "forecast_units_7_days": 14.0,
        "forecast_units_30_days": 60.0,
        "slotting_pending": 2,
        "slotting_seconds_saved_per_day": 40.0,
    }
    assert (
        client.get("/api/v1/ml/summary", headers=as_(db_session, RoleName.CUSTOMER)).status_code
        == 403
    )


def test_summary_before_scoring(client: TestClient, db_session: Session) -> None:
    body = client.get("/api/v1/ml/summary", headers=as_(db_session, RoleName.MANAGER)).json()
    assert body["as_of"] is None and body["stockouts_pending"] == 0
    assert body["forecast_units_7_days"] == 0
