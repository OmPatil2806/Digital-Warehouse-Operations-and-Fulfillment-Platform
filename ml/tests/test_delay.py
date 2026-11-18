"""Order-delay prediction: dispatch-time features without leakage, the baseline, the
networks, risk levels and reasons, and a full training run."""

import dataclasses
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.models.ml import ModelStatus, ModelVersion
from baselines.delay import LogisticBaseline
from data_generation.context import GenerationContext
from data_generation.database import sqlite_url
from feature_engineering.delay_features import (
    NUMERIC,
    PRE_DISPATCH_STATUSES,
    SEQUENCE_STEPS,
    _carrier_late_rate,
    build_delay_set,
)
from models.delay_prediction.explain import FACTORS, reasons, risk_level
from training import keras_setup
from training.config import load_config
from training.data import read_frame

Simulated = tuple[GenerationContext, Engine, dict]


@pytest.fixture(scope="module")
def delay_set(with_orders: Simulated):
    _, engine, _ = with_orders
    return build_delay_set(engine)


def test_one_row_per_delivered_shipment(with_orders: Simulated, delay_set) -> None:
    _, engine, _ = with_orders
    truth = read_frame(
        engine,
        "SELECT order_id, date(delivered_at) > expected_delivery_date AS late FROM shipments "
        "WHERE delivered_at IS NOT NULL ORDER BY order_id",
    ).set_index("order_id")["late"]
    assert len(delay_set) == len(truth)
    labels = pd.Series(delay_set.label, index=delay_set.order_ids).sort_index()
    assert (labels.to_numpy() == truth.to_numpy()).all()
    assert list(delay_set.numeric.columns) == list(NUMERIC)
    assert delay_set.categorical.sum(axis=1).tolist() == [4] * len(delay_set)  # 4 groups
    assert delay_set.wide.sum(axis=1).tolist() == [3] * len(delay_set)  # 3 crosses
    assert (np.diff(delay_set.shipped_day.astype("int64")) >= 0).all()  # in dispatch order


def test_sequences_stop_at_dispatch(with_orders: Simulated, delay_set) -> None:
    _, engine, _ = with_orders
    assert delay_set.sequence.shape[1:] == (SEQUENCE_STEPS, len(PRE_DISPATCH_STATUSES) + 1)
    statuses = delay_set.sequence[:, :, :-1]
    newest = statuses[:, -1, :].argmax(axis=1)
    assert (newest == PRE_DISPATCH_STATUSES.index("shipped")).all()  # last event: dispatch
    assert "delayed" not in PRE_DISPATCH_STATUSES and "delivered" not in PRE_DISPATCH_STATUSES
    hours = delay_set.sequence[:, :, -1]
    filled = statuses.sum(axis=2) > 0
    first = filled.argmax(axis=1)
    assert (hours[np.arange(len(hours)), first] < 1).all()  # starts with the order
    waited = delay_set.numeric["waited_for_stock"].to_numpy() == 1
    backorder = PRE_DISPATCH_STATUSES.index("partially_allocated"), PRE_DISPATCH_STATUSES.index(
        "backordered"
    )
    seen = statuses[:, :, list(backorder)].sum(axis=(1, 2)) > 0
    assert (seen[waited]).all()


def test_carrier_rate_uses_only_earlier_deliveries() -> None:
    shipments = pd.DataFrame(
        {
            "carrier_id": [1, 1, 1, 1],
            "shipped_day": ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"],
            "delivered_day": ["2026-01-03", "2026-01-04", "2026-01-07", "2026-01-08"],
            "late": [1, 1, 0, 0],
        }
    )
    rates = _carrier_late_rate(shipments)
    prior = 0.1 * 50 / 50
    assert rates[0] == pytest.approx(prior) and rates[1] == pytest.approx(prior)
    assert rates[2] == pytest.approx((2 + 5) / (2 + 50))  # the two January deliveries
    # its own outcome (late = 0, delivered on the 7th) is not in its own feature
    assert rates[3] == pytest.approx((2 + 5) / (2 + 50))


def test_logistic_baseline_learns_a_clear_signal() -> None:
    rng = np.random.default_rng(0)
    numeric = rng.normal(size=(400, 3))
    label = (numeric[:, 0] > 0.5).astype(float)
    baseline = LogisticBaseline().fit(numeric, np.zeros((400, 1)), label)
    p = baseline.predict({"numeric": numeric, "categorical": np.zeros((400, 1))})
    assert p[label == 1].mean() > 0.7 > 0.3 > p[label == 0].mean()


def test_risk_levels() -> None:
    assert risk_level(0.7, 0.2) == "high" and risk_level(0.3, 0.2) == "medium"
    assert risk_level(0.1, 0.2) == "low" and risk_level(0.55, 0.6) == "low"


def test_reasons_find_the_factor_that_matters() -> None:
    column = NUMERIC.index("waited_for_stock")
    numeric = np.zeros((2, len(NUMERIC)), "float32")
    numeric[0, column] = 1

    def predict(inputs):  # risk only from waiting for stock
        return 0.1 + 0.5 * inputs["numeric"][:, column]

    found = reasons(predict, {"numeric": numeric}, np.zeros(len(NUMERIC)))
    assert found == [("Waited for stock",), ()]
    assert set(FACTORS) >= {"Large order", "Peak season", "Unreliable carrier", "Busy warehouse"}


@pytest.mark.parametrize("name", ["dense", "wide_deep", "deep_cross", "lstm_events"])
def test_networks_build_train_and_reload(name: str, tmp_path: Path) -> None:
    from models.delay_prediction import ARCHITECTURES
    from training.train_delay import model_inputs

    rng = np.random.default_rng(0)
    x = {
        "numeric": rng.normal(size=(64, len(NUMERIC))).astype("float32"),
        "categorical": np.eye(6, dtype="float32")[rng.integers(0, 6, 64)],
        "wide": np.eye(5, dtype="float32")[rng.integers(0, 5, 64)],
        "sequence": rng.random((64, SEQUENCE_STEPS, 4)).astype("float32"),
    }
    y = (x["numeric"][:, 0] > 0).astype("float32")
    keras_setup.set_seeds(4)
    model = ARCHITECTURES[name](
        {k: v.shape[1:] for k, v in x.items()}, {"units": [8], "lstm_units": 4}, 0.01, x
    )
    model.fit(model_inputs(model, x), y, epochs=1, batch_size=64, verbose=0)
    out = model.predict(model_inputs(model, x), verbose=0)
    assert out.shape == (64, 1) and ((out > 0) & (out < 1)).all()
    path = keras_setup.save_model(model, tmp_path / f"{name}.keras")
    again = keras_setup.load_model(path).predict(model_inputs(model, x), verbose=0)
    assert np.allclose(again, out, atol=1e-6)


def test_cross_layer_by_hand() -> None:
    from models.delay_prediction.deep_cross import CrossLayer

    layer = CrossLayer()
    x0 = np.array([[1.0, 2.0]], "float32")
    layer.build([(None, 2), (None, 2)])
    layer.dense.set_weights([np.eye(2, dtype="float32"), np.ones(2, "float32")])
    # x0 * (I x + 1) + x with x = x0: [1*(1+1)+1, 2*(2+1)+2] = [3, 8]
    assert np.allclose(layer([x0, x0]).numpy(), [[3.0, 8.0]])


def test_training_run(with_orders: Simulated, tmp_path: Path, monkeypatch) -> None:
    from training import train_delay

    _, engine, _ = with_orders
    database = tmp_path / "train.db"
    shutil.copy(str(engine.url.database), database)
    monkeypatch.setattr(keras_setup, "ARTIFACT_DIR", tmp_path / "artifacts")
    config = dataclasses.replace(
        load_config("delay_prediction"), max_epochs=2, models={"deep_cross": {"units": [8]}}
    )
    report = tmp_path / "report.md"
    outcome = train_delay.run(
        database, config=config, report=lambda _: None, write_report=report, examples=3
    )
    assert [r.name for r in outcome.results] == ["logistic_regression", "deep_cross"]
    for result in outcome.results:
        assert 0 <= result.test["pr_auc"] <= 1 and 0 <= result.test["threshold"] <= 1
    assert len(outcome.examples) == 3
    probabilities = [e.probability for e in outcome.examples]
    assert probabilities == sorted(probabilities, reverse=True)
    assert all(e.level in {"low", "medium", "high"} for e in outcome.examples)
    with Session(create_engine(sqlite_url(database))) as session:
        rows = session.scalars(
            select(ModelVersion).where(ModelVersion.use_case == "delay_prediction")
        ).all()
    assert len(rows) == 2 and sum(r.status == ModelStatus.SELECTED for r in rows) == 1
    assert next(r for r in rows if r.is_baseline).artifact_path is None
    text = report.read_text()
    assert "| Model | Type | pr_auc" in text and "## Riskiest shipments" in text
