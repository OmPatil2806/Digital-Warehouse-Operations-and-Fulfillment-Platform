"""Demand forecasting: features without leakage, baselines, networks, the training run."""

import dataclasses
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models.ml import ModelStatus, ModelVersion
from baselines.demand import moving_average, seasonal_naive
from data_generation.context import GenerationContext
from feature_engineering.demand_features import (
    DemandData,
    build_demand_data,
    calendar,
    load_daily_demand,
    make_windows,
    origins_between,
    product_scale,
)
from training import keras_setup
from training.config import load_config
from training.data import history_range, read_frame

Simulated = tuple[GenerationContext, Engine, dict]


@pytest.fixture(scope="module")
def demand(with_orders: Simulated) -> DemandData:
    _, engine, _ = with_orders
    first, last = history_range(engine)
    return build_demand_data(engine, first, last)


def toy(units: np.ndarray) -> DemandData:
    products, days = units.shape
    return DemandData(
        product_ids=np.arange(1, products + 1),
        categories=np.zeros(products, dtype=int),
        category_names=["Only"],
        first=date(2026, 1, 5),  # a Monday
        units=units.astype("float32"),
        promo=np.zeros_like(units, dtype="float32"),
    )


# ------------------------------------------------------------------- features
def test_daily_demand_matches_the_order_lines(with_orders: Simulated, demand: DemandData) -> None:
    _, engine, _ = with_orders
    total = read_frame(engine, "SELECT SUM(quantity) AS n FROM order_items").n[0]
    products = read_frame(engine, "SELECT COUNT(*) AS n FROM products").n[0]
    first, last = history_range(engine)
    assert demand.units.shape == (products, (last - first).days + 1)  # every product and day
    assert demand.units.sum() == total
    daily = load_daily_demand(engine)
    assert set(daily.columns) == {"product_id", "day", "units", "promo"}
    assert demand.promo.max() == 1 and demand.promo.sum() == daily.promo.sum()
    assert len(demand.category_names) == 8


def test_calendar_features() -> None:
    cal = calendar(date(2026, 1, 5), 8)  # Monday ... next Monday
    assert cal.shape == (8, 4)
    assert np.allclose(cal[0, :2], cal[7, :2])  # same weekday, same values
    assert cal[0, 0] == pytest.approx(0) and cal[0, 1] == pytest.approx(1)
    assert np.allclose(np.hypot(cal[:, 0], cal[:, 1]), 1)


def test_scale_uses_only_the_past() -> None:
    data = toy(np.array([[2, 4, 6, 100], [0, 0, 0, 9]]))
    assert list(product_scale(data, until=3)) == pytest.approx([4, 0.1])  # floor for slow
    with pytest.raises(ValueError):
        product_scale(data, until=0)


def test_origins_fit_inside_their_period() -> None:
    assert origins_between(0, 99, window=10, horizon=5, stride=20) == [15, 35, 55, 75, 95]
    assert origins_between(50, 59, window=10, horizon=5, stride=7) == []
    assert origins_between(90, 99, window=4, horizon=5, stride=1) == [94, 95]


def test_windows_never_see_the_forecast_days() -> None:
    units = np.arange(40, dtype="float32").reshape(2, 20) + 1
    data = toy(units)
    scale = np.array([2.0, 4.0], dtype="float32")
    w = make_windows(data, [10, 15], window=5, horizon=3, scale=scale)
    assert len(w) == 4 and list(w.products) == [0, 1, 0, 1] and list(w.origins) == [10, 10, 15, 15]
    # history = the 5 days before the origin, scaled; target = the 3 days from it, in units
    assert np.allclose(w.history[0, :, 0] * 2, units[0, 5:10])
    assert np.allclose(w.raw_history()[1], units[1, 5:10])
    assert np.allclose(w.target[3], units[1, 15:18])
    assert w.history[:, :, 0].max() * 4 < units[1, 15]  # nothing from the horizon
    assert np.allclose(w.future[2], calendar(data.first, 20)[15:18])
    assert w.static[0, 0] == 1 and w.static[1, -1] == pytest.approx(np.log1p(4))
    assert w.history.shape == (4, 5, 6) and w.static.shape == (4, 2)
    small = w.subset(np.array([3]))
    assert len(small) == 1 and np.allclose(small.target[0], w.target[3])
    with pytest.raises(ValueError, match="outside"):
        make_windows(data, [3], window=5, horizon=3, scale=scale)
    with pytest.raises(ValueError, match="no forecast origins"):
        make_windows(data, [], window=5, horizon=3, scale=scale)


# ------------------------------------------------------------------- baselines
def test_moving_average_by_hand() -> None:
    history = np.array([[0, 0, 4, 4] * 7])  # 28 days, average 2
    forecast = moving_average(history, horizon=3)
    assert forecast.shape == (1, 3, 3)
    assert np.allclose(forecast[0, :, 1], 2)
    assert np.allclose(forecast[0, :, 0], 0) and np.allclose(forecast[0, :, 2], 4)


def test_seasonal_naive_repeats_last_week() -> None:
    week = np.array([1, 2, 3, 4, 5, 6, 7], dtype=float)
    history = np.concatenate([week * 2, week, week, week])[None, :]  # 4 weeks
    forecast = seasonal_naive(history, horizon=10)
    assert np.allclose(forecast[0, :, 1], [1, 2, 3, 4, 5, 6, 7, 1, 2, 3])
    assert np.allclose(forecast[0, :7, 2], week * 1.7)  # 90th percentile of (x, x, x, 2x)
    assert (forecast[:, :, 0] <= forecast[:, :, 1]).all()
    with pytest.raises(ValueError, match="days of history"):
        seasonal_naive(history[:, :20], horizon=3)


# -------------------------------------------------------------------- networks
def test_forecast_loss_by_hand() -> None:
    from models.demand_forecasting.common import forecast_loss

    actual = np.array([[2.0, 0.0]])
    predicted = np.array([[[1.0, 1.0, 3.0], [1.0, 1.0, 3.0]]])  # low, expected, high
    # expected: mean((2-1)^2, (0-1)^2) = 1
    # low (q=0.1): errors +1 -> 0.1, -1 -> 0.9 -> mean 0.5
    # high (q=0.9): errors -1 -> 0.1, -3 -> 0.3 -> mean 0.2
    assert float(forecast_loss(actual, predicted)) == pytest.approx(1.7)


@pytest.mark.parametrize("name", ["lstm", "gru", "cnn_lstm", "transformer"])
def test_each_network_builds_trains_and_reloads(name: str, tmp_path: Path) -> None:
    from models.demand_forecasting import ARCHITECTURES

    shapes = {"window": 14, "horizon": 7, "history_features": 6, "future_features": 4, "static": 3}
    keras_setup.set_seeds(1)
    model = ARCHITECTURES[name](shapes, {"units": 4, "hidden": 8, "width": 8, "heads": 2}, 0.01)
    rng = np.random.default_rng(0)
    inputs = {
        "history": rng.normal(size=(16, 14, 6)).astype("float32"),
        "future": rng.normal(size=(16, 7, 4)).astype("float32"),
        "static": rng.normal(size=(16, 3)).astype("float32"),
    }
    target = rng.poisson(1.0, size=(16, 7)).astype("float32")
    model.fit(inputs, target, epochs=1, batch_size=16, verbose=0)  # one training step
    out = model.predict(inputs, verbose=0)
    assert out.shape == (16, 7, 3)
    assert (out[..., 0] <= out[..., 1]).all() and (out[..., 1] <= out[..., 2]).all()
    path = keras_setup.save_model(model, tmp_path / f"{name}.keras")
    assert np.allclose(keras_setup.load_model(path).predict(inputs, verbose=0), out, atol=1e-5)


# ----------------------------------------------------------------- training run
def test_training_run_registers_and_selects(
    with_orders: Simulated, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from training import train_demand

    _, engine, _ = with_orders
    database = tmp_path / "train.db"
    shutil.copy(str(engine.url.database), database)
    monkeypatch.setattr(keras_setup, "ARTIFACT_DIR", tmp_path / "artifacts")
    config = dataclasses.replace(
        load_config("demand_forecasting"),
        max_epochs=2,
        features={"window": 28, "horizon": 14, "train_stride": 14, "eval_stride": 14},
        models={"gru": {"units": 4, "hidden": 8}},
    )
    lines: list[str] = []
    report = tmp_path / "report.md"
    outcome = train_demand.run(database, config=config, report=lines.append, write_report=report)

    names = [r.name for r in outcome.results]
    assert names == ["moving_average", "seasonal_naive", "gru"]
    gru = outcome.results[-1]
    assert gru.artifact is not None and gru.artifact.exists() and 1 <= gru.epochs <= 2
    assert not list(gru.artifact.parent.glob("*.checkpoint.keras"))  # cleaned up
    assert set(gru.test) >= {"wape", "mae", "rmse", "coverage_80", "wape_7d_total", "wape_totals"}
    assert "wape_30d_total" not in gru.test  # 14-day horizon
    first, last = history_range(engine)
    days = (last - first).days + 1
    assert outcome.windows["test"] == 50 * len(
        origins_between(days - 90 - 28, days - 1, window=28, horizon=14, stride=14)
    )

    from sqlalchemy import create_engine

    from data_generation.database import sqlite_url

    with Session(create_engine(sqlite_url(database))) as session:
        rows = session.scalars(select(ModelVersion)).all()
    assert len(rows) == 3 and sum(r.status == ModelStatus.SELECTED for r in rows) == 1
    assert {r.model_name for r in rows if r.is_baseline} == {"moving_average", "seasonal_naive"}
    stored = next(r for r in rows if r.model_name == "gru")
    assert stored.artifact_path.endswith(".keras") and stored.hyperparameters["window"] == 28
    assert stored.metric("wape_totals") == pytest.approx(gru.test["wape_totals"])
    assert outcome.selection.model_name in names
    text = report.read_text()
    assert "| Model | Type | wape_totals" in text and "(selected)" in text
    assert any(line.startswith("Selected:") for line in lines)


def test_unknown_model_is_refused(with_orders: Simulated) -> None:
    from training import train_demand

    _, engine, _ = with_orders
    with pytest.raises(ValueError, match="unknown model"):
        train_demand.run(Path(str(engine.url.database)), models=["prophet"], write_report=None)
