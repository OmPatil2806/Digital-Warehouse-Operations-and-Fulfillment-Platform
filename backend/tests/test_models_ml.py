"""Tests for the model registry tables (model_versions, model_metrics)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ml import MetricSplit, ModelMetric, ModelStatus, ModelVersion, UseCase


def model(name: str = "lstm", version: str = "v1", **overrides: object) -> ModelVersion:
    values: dict[str, object] = {
        "use_case": UseCase.DEMAND,
        "model_name": name,
        "version": version,
        "dataset_version": "full-seed20261111-2026-11-10",
        "features": ["units_lag_7", "weekday"],
        "hyperparameters": {"units": 32, "learning_rate": 0.001},
        "artifact_path": f"artifacts/demand_forecasting/{name}/{version}.keras",
        "trained_at": datetime(2026, 11, 16, 12, tzinfo=UTC),
        "train_seconds": 42.5,
    }
    values.update(overrides)
    return ModelVersion(**values)


def test_model_with_metrics(db_session: Session) -> None:
    lstm = model()
    lstm.metrics = [
        ModelMetric(split=MetricSplit.VALIDATION, name="wape", value=0.31),
        ModelMetric(split=MetricSplit.TEST, name="wape", value=0.29),
    ]
    db_session.add(lstm)
    db_session.commit()
    db_session.expire_all()

    stored = db_session.scalars(select(ModelVersion)).one()
    assert stored.status == ModelStatus.CANDIDATE and stored.is_baseline is False
    assert stored.features == ["units_lag_7", "weekday"]
    assert stored.hyperparameters == {"units": 32, "learning_rate": 0.001}
    assert stored.trained_at == datetime(2026, 11, 16, 12, tzinfo=UTC)
    assert stored.metric("wape") == pytest.approx(0.29)
    assert stored.metric("wape", MetricSplit.VALIDATION) == pytest.approx(0.31)
    assert stored.metric("mae") is None


def test_baseline_without_artifact(db_session: Session) -> None:
    db_session.add(model("moving_average", is_baseline=True, artifact_path=None))
    db_session.commit()


def test_versions_are_unique_per_model(db_session: Session) -> None:
    db_session.add_all([model(), model("gru"), model(version="v2")])
    db_session.commit()
    db_session.add(model())
    with pytest.raises(IntegrityError, match="UNIQUE"):
        db_session.commit()


def test_only_one_selected_model_per_use_case(db_session: Session) -> None:
    db_session.add_all(
        [
            model(status=ModelStatus.SELECTED),
            model("gru", status=ModelStatus.RETIRED),
            model("dense", use_case=UseCase.DELAY, status=ModelStatus.SELECTED),
        ]
    )
    db_session.commit()
    db_session.add(model("transformer", status=ModelStatus.SELECTED))
    with pytest.raises(IntegrityError, match="UNIQUE"):
        db_session.commit()


@pytest.mark.parametrize(
    ("field", "value"),
    [("use_case", "weather"), ("status", "deployed"), ("train_seconds", -1.0)],
)
def test_check_constraints(db_session: Session, field: str, value: object) -> None:
    db_session.add(model(**{field: value}))
    with pytest.raises(IntegrityError, match="CHECK"):
        db_session.commit()


def test_one_value_per_metric_and_split(db_session: Session) -> None:
    lstm = model()
    lstm.metrics = [
        ModelMetric(split=MetricSplit.TEST, name="mae", value=1.0),
        ModelMetric(split=MetricSplit.TEST, name="mae", value=2.0),
    ]
    db_session.add(lstm)
    with pytest.raises(IntegrityError, match="UNIQUE"):
        db_session.commit()


def test_metric_split_is_checked(db_session: Session) -> None:
    lstm = model()
    lstm.metrics = [ModelMetric(split="train", name="mae", value=1.0)]
    db_session.add(lstm)
    with pytest.raises(IntegrityError, match="CHECK"):
        db_session.commit()


def test_metrics_are_deleted_with_their_model(db_session: Session) -> None:
    lstm = model()
    lstm.metrics = [ModelMetric(split=MetricSplit.TEST, name="mae", value=1.0)]
    db_session.add(lstm)
    db_session.commit()
    db_session.delete(lstm)
    db_session.commit()
    assert db_session.scalars(select(ModelMetric)).all() == []
