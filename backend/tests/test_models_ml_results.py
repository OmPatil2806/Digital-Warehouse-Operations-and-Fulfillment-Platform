"""Tests for the ML prediction tables."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ml import ModelVersion, UseCase
from app.models.ml_results import (
    RESULT_TABLES,
    DecisionStatus,
    DemandForecast,
    MovementClassification,
    ProductRecommendation,
    ReorderRecommendation,
)
from tests.factories import create_bin, create_category, create_product

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)


def model(db: Session, use_case: UseCase = UseCase.DEMAND) -> ModelVersion:
    row = ModelVersion(
        use_case=use_case,
        model_name="lstm",
        version="v1",
        dataset_version="d",
        features=[],
        hyperparameters={},
        artifact_path="artifacts/x.keras",
        trained_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def common(model_row: ModelVersion) -> dict:
    return {"model_version_id": model_row.id, "scored_at": NOW, "as_of": date(2026, 11, 10)}


def test_one_table_per_use_case() -> None:
    assert set(RESULT_TABLES) == {u.value for u in UseCase}


def test_forecast_range_must_be_ordered(db_session: Session) -> None:
    product = create_product(db_session, create_category(db_session))
    m = model(db_session)
    ok = DemandForecast(
        product_id=product.id,
        day=date(2026, 11, 11),
        expected_units=5,
        low_units=2,
        high_units=9,
        **common(m),
    )
    db_session.add(ok)
    db_session.commit()
    db_session.add(
        DemandForecast(
            product_id=product.id,
            day=date(2026, 11, 12),
            expected_units=5,
            low_units=6,
            high_units=9,
            **common(m),
        )
    )
    with pytest.raises(IntegrityError, match="CHECK"):
        db_session.commit()


def test_reorder_recommendation_decision_defaults_and_checks(db_session: Session) -> None:
    product = create_product(db_session, create_category(db_session))
    warehouse = create_bin(db_session).shelf.rack.zone.warehouse
    m = model(db_session, UseCase.REORDER)
    values = {
        "product_id": product.id,
        "warehouse_id": warehouse.id,
        "probability": 0.7,
        "priority": "high",
        "reorder_date": date(2026, 11, 10),
        "quantity": 12,
        "reasons": ["Low available stock"],
        **common(m),
    }
    rec = ReorderRecommendation(**values)
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)
    assert rec.status == DecisionStatus.PENDING and rec.reasons == ["Low available stock"]
    assert rec.decided_by_id is None and rec.purchase_order_id is None
    for bad in ({"probability": 1.5}, {"priority": "urgent"}, {"quantity": -1}):
        db_session.add(ReorderRecommendation(**{**values, **bad}))
        with pytest.raises(IntegrityError, match="CHECK"):
            db_session.commit()
        db_session.rollback()


def test_class_and_self_recommendation_checks(db_session: Session) -> None:
    category = create_category(db_session)
    product = create_product(db_session, category)
    m = model(db_session, UseCase.MOVEMENT)
    db_session.add(
        MovementClassification(
            product_id=product.id, movement_class="speedy", picks_per_day=1.0, **common(m)
        )
    )
    with pytest.raises(IntegrityError, match="CHECK"):
        db_session.commit()
    db_session.rollback()
    m = model(db_session, UseCase.RECOMMENDATION)
    db_session.add(
        ProductRecommendation(
            product_id=product.id, recommended_product_id=product.id, rank=1, score=1.0, **common(m)
        )
    )
    with pytest.raises(IntegrityError, match="CHECK"):
        db_session.commit()
