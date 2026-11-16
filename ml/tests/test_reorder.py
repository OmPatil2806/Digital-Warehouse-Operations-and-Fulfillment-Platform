"""Reorder recommendation: stock history, snapshots without leakage, baseline, networks,
recommendations with reasons, and a full training run."""

import dataclasses
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.models.ml import ModelStatus, ModelVersion
from baselines.reorder import SAFETY_DAYS, reorder_point, reorder_point_score
from data_generation.context import GenerationContext
from data_generation.database import sqlite_url
from feature_engineering.reorder_features import (
    NUMERIC,
    StockHistory,
    build_stock_history,
    make_snapshots,
    snapshot_days,
)
from models.reorder.recommend import FACTORS, contributions, priority, recommend
from training import keras_setup
from training.config import load_config
from training.data import history_range, read_frame

Simulated = tuple[GenerationContext, Engine, dict]


@pytest.fixture(scope="module")
def stock(with_orders: Simulated) -> StockHistory:
    _, engine, _ = with_orders
    return build_stock_history(engine, *history_range(engine))


def toy(available: np.ndarray, demand: np.ndarray | None = None) -> StockHistory:
    series, days = available.shape
    return StockHistory(
        first=date(2026, 1, 1),
        product_ids=np.arange(1, series + 1),
        warehouse_ids=np.ones(series, int),
        available=available.astype("float32"),
        on_order=np.zeros_like(available, "float32"),
        demand=(np.ones_like(available) if demand is None else demand).astype("float32"),
        categories=np.zeros(series, int),
        category_names=["Only"],
        warehouse_count=1,
        lead_days=np.full(series, 10.0, "float32"),
        reliability=np.full(series, 0.9, "float32"),
    )


# ------------------------------------------------------------------ stock history
def test_stock_history_ends_at_the_current_stock(with_orders: Simulated, stock) -> None:
    _, engine, _ = with_orders
    now = read_frame(
        engine,
        "SELECT i.product_id, SUM(quantity_on_hand - quantity_reserved - quantity_damaged) AS a "
        "FROM inventory i GROUP BY 1",
    ).set_index("product_id")["a"]
    last = stock.available[:, -1]
    for product_id, units in now.items():
        assert last[stock.product_ids == product_id].sum() == pytest.approx(units)
    assert (stock.available >= 0).all() and (stock.on_order >= 0).all()
    sold = read_frame(
        engine,
        "SELECT SUM(quantity) AS n FROM order_items oi JOIN orders o "
        "ON o.id = oi.order_id WHERE o.warehouse_id IS NOT NULL",
    ).n[0]
    assert stock.demand.sum() == sold
    assert stock.on_order.max() > 0 and 0 < stock.reliability.max() <= 1


def test_snapshot_days() -> None:
    assert snapshot_days(0, 100, horizon=14, stride=30, warmup=56) == [56, 86]
    assert snapshot_days(90, 100, horizon=14, stride=7, warmup=56) == []


def test_labels_and_out_of_stock_rows() -> None:
    available = np.full((3, 100), 5.0)
    available[0, 70] = 0  # runs out 10 days after day 60
    available[1, 60] = 0  # already out on the snapshot day: left out
    snaps = make_snapshots(toy(available), [60], horizon=14)
    assert list(snaps.series) == [0, 2] and list(snaps.label) == [1, 0]
    assert len(make_snapshots(toy(available), [60], horizon=5)) == 2
    assert make_snapshots(toy(available), [60], horizon=5).label[0] == 0  # day 70 too late
    every = make_snapshots(toy(available), [60], horizon=14, include_out_of_stock=True)
    assert len(every) == 3
    late = make_snapshots(toy(available), [95], horizon=14)
    assert np.isnan(late.label).all()  # the look-ahead passes the end: unknown


def test_features_use_only_the_past() -> None:
    rng = np.random.default_rng(0)
    demand = rng.poisson(3, size=(2, 120)).astype(float)
    available = np.full((2, 120), 50.0)
    before = make_snapshots(toy(available, demand), [80], horizon=14)
    demand[:, 81:] *= 10  # the future changes
    available[:, 81:] = 0
    after = make_snapshots(toy(available, demand), [80], horizon=14)
    assert np.allclose(before.numeric.to_numpy(), after.numeric.to_numpy())
    assert np.allclose(before.sequence, after.sequence)
    assert list(before.label) == [0, 0] and list(after.label) == [1, 1]
    assert np.exp(before.numeric["log_demand_7"].iloc[0]) - 1 == pytest.approx(
        demand[0, 74:81].mean()
    )
    assert before.sequence.shape == (2, 28, 2)
    assert before.categorical.sum(axis=1).tolist() == [2, 2]  # category + warehouse
    assert before.wide.sum(axis=1).tolist() == [2, 2]  # cover x peak + month
    assert list(before.numeric.columns) == list(NUMERIC)
    with pytest.raises(ValueError, match="56 days of history"):
        make_snapshots(toy(available, demand), [30], horizon=14)


# ----------------------------------------------------------------------- baseline
def test_reorder_point_baseline_by_hand() -> None:
    assert reorder_point(np.array([2.0]), np.array([10.0]))[0] == 2 * (10 + SAFETY_DAYS)
    score = reorder_point_score(
        np.array([2.0, 2.0, 0.0]), np.array([10.0] * 3), np.array([36.0, 0.0, 5.0])
    )
    assert list(score) == pytest.approx([0.5, 1.0, 0.0])  # at, below, no demand


# ----------------------------------------------------------------- recommendations
def test_priorities() -> None:
    assert priority(0.7, 0.3) == "high" and priority(0.4, 0.3) == "medium"
    assert priority(0.2, 0.3) == "low" and priority(0.75, 0.8) == "low"


def test_recommendations_dates_quantities_reasons() -> None:
    available = np.full((2, 100), 100.0)
    snaps = make_snapshots(toy(available), [80], horizon=14)  # demand 1/day, lead 10
    stock = toy(available)
    effects = {name: np.zeros(2) for name in FACTORS}
    effects["Low available stock"] = np.array([0.30, 0.0])
    effects["Seasonal peak ahead"] = np.array([0.10, 0.01])
    recs = recommend(
        snaps,
        np.array([0.2, 0.9]),
        threshold=0.5,
        product_ids=stock.product_ids,
        warehouse_ids=stock.warehouse_ids,
        lead_days=stock.lead_days,
        today=date(2026, 3, 22),
        factor_effects=effects,
    )
    first, second = recs  # highest risk first
    assert (first.product_id, first.priority, first.reorder_date) == (2, "high", date(2026, 3, 22))
    assert first.quantity == SAFETY_DAYS  # plenty in stock, but at risk: a safety buffer
    assert first.reasons == ()  # 0.01 is below the reporting limit
    # low risk: reorder when 100 units fall to the reorder point 1 x (10 + 8) -> 82 days
    assert second.priority == "low" and second.reorder_date == date(2026, 6, 12)
    assert second.quantity == 0 and second.reasons == ("Low available stock", "Seasonal peak ahead")


def test_contributions_find_the_factor_that_matters() -> None:
    available = np.full((4, 100), 100.0)
    available[:2] = 3
    snaps = make_snapshots(toy(available), [80], horizon=14)
    column = NUMERIC.index("log_available")

    def predict(inputs: dict) -> np.ndarray:  # risk depends on available stock only
        return 1 / (1 + inputs["numeric"][:, column])

    means = snaps.numeric.to_numpy("float32").mean(axis=0)
    effects = contributions(predict, snaps, means)
    assert effects["Low available stock"][0] > 0.1 > effects["Low available stock"][3] * -1
    assert all(np.allclose(v, 0) for k, v in effects.items() if k != "Low available stock")


# ----------------------------------------------------------------------- networks
@pytest.mark.parametrize("name", ["dense", "wide_deep", "lstm"])
def test_each_network_builds_trains_and_reloads(name: str, tmp_path: Path) -> None:
    from models.reorder import ARCHITECTURES
    from training.train_reorder import model_inputs

    rng = np.random.default_rng(0)
    inputs = {
        "numeric": rng.normal(size=(64, len(NUMERIC))).astype("float32"),
        "categorical": np.eye(5, dtype="float32")[rng.integers(0, 5, 64)],
        "wide": np.eye(6, dtype="float32")[rng.integers(0, 6, 64)],
        "sequence": rng.normal(size=(64, 7, 2)).astype("float32"),
    }
    label = (inputs["numeric"][:, 0] > 0).astype("float32")
    shapes = {k: v.shape[1:] for k, v in inputs.items()}
    keras_setup.set_seeds(3)
    model = ARCHITECTURES[name](shapes, {"units": [8], "lstm_units": 4}, 0.01, inputs)
    model.fit(model_inputs(model, inputs), label, epochs=1, batch_size=64, verbose=0)
    out = model.predict(model_inputs(model, inputs), verbose=0)
    assert out.shape == (64, 1) and ((out > 0) & (out < 1)).all()
    path = keras_setup.save_model(model, tmp_path / f"{name}.keras")
    again = keras_setup.load_model(path).predict(model_inputs(model, inputs), verbose=0)
    assert np.allclose(again, out, atol=1e-6)


# ------------------------------------------------------------------- training run
def test_training_run(with_orders: Simulated, tmp_path: Path, monkeypatch) -> None:
    from training import train_reorder

    _, engine, _ = with_orders
    database = tmp_path / "train.db"
    shutil.copy(str(engine.url.database), database)
    monkeypatch.setattr(keras_setup, "ARTIFACT_DIR", tmp_path / "artifacts")
    config = dataclasses.replace(
        load_config("reorder"),
        max_epochs=2,
        features={"horizon": 14, "sequence_days": 14, "train_stride": 7, "eval_stride": 7},
        models={"wide_deep": {"units": [8]}},
    )
    report = tmp_path / "report.md"
    outcome = train_reorder.run(
        database, config=config, report=lambda _: None, write_report=report, top=5
    )
    assert [r.name for r in outcome.results] == ["reorder_point", "wide_deep"]
    for result in outcome.results:
        assert 0 <= result.test["threshold"] <= 1 and 0 <= result.test["pr_auc"] <= 1
        assert set(result.test) >= {"precision", "recall", "f1", "roc_auc", "brier", "ece"}
    assert 0 < outcome.positives["train"] < 0.5
    assert len(outcome.recommendations) == 5
    probabilities = [r.probability for r in outcome.recommendations]
    assert probabilities == sorted(probabilities, reverse=True)
    with Session(create_engine(sqlite_url(database))) as session:
        rows = session.scalars(select(ModelVersion).where(ModelVersion.use_case == "reorder")).all()
    assert len(rows) == 2 and sum(r.status == ModelStatus.SELECTED for r in rows) == 1
    text = report.read_text()
    assert "| Model | Type | pr_auc" in text and "## Top recommendations on" in text
