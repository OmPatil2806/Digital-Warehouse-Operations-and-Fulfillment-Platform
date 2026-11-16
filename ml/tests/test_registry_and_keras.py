"""Model registry, dataset versions and the TensorFlow/Keras plumbing (16.8: "model build
and one training step on tiny data")."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ml import ModelStatus, ModelVersion
from data_generation.context import GenerationContext
from data_generation.database import prepare_database, sqlite_url
from registry.register_model import RegistryError, register_model, select_best, selected_model
from training import keras_setup
from training.data import DatasetError, dataset_version, history_range, open_dataset, read_frame

Simulated = tuple[GenerationContext, Engine, dict]


@pytest.fixture()
def registry(tmp_path: Path) -> Engine:
    return prepare_database(tmp_path / "registry.db")


def add(engine: Engine, name: str, test_wape: float, *, baseline: bool = False, **extra) -> int:
    values = {
        "use_case": "demand_forecasting",
        "model_name": name,
        "version": "20261116-1200",
        "dataset_version": "orders500-to2026-11-10-abc",
        "features": ["lag_7"],
        "hyperparameters": {"units": 8},
        "metrics": {"validation": {"wape": test_wape + 0.01}, "test": {"wape": test_wape}},
        "artifact_path": None if baseline else f"artifacts/x/{name}.keras",
        "is_baseline": baseline,
        "train_seconds": 1.5,
    }
    values.update(extra)
    return register_model(engine, **values)


# ----------------------------------------------------------------------- registry
def test_register_stores_everything(registry: Engine) -> None:
    model_id = add(registry, "lstm", 0.3, notes="first try")
    with Session(registry) as session:
        row = session.get(ModelVersion, model_id)
        assert row is not None and row.status == ModelStatus.CANDIDATE
        assert (row.features, row.hyperparameters, row.notes) == (
            ["lag_7"],
            {"units": 8},
            "first try",
        )
        assert row.metric("wape") == pytest.approx(0.3)
        assert row.metric("wape", "validation") == pytest.approx(0.31)
        assert row.trained_at.tzinfo is not None


def test_best_neural_model_selected_only_if_it_beats_the_baseline(registry: Engine) -> None:
    baseline = add(registry, "moving_average", 0.40, baseline=True)
    lstm, gru = add(registry, "lstm", 0.35), add(registry, "gru", 0.30)
    choice = select_best(
        registry, "demand_forecasting", [baseline, lstm, gru], metric="wape", higher_is_better=False
    )
    assert (choice.model_name, choice.model_version_id) == ("gru", gru)
    assert "gru beat the baseline moving_average: wape 0.3 vs 0.4" in choice.reason
    assert selected_model(registry, "demand_forecasting").model_name == "gru"


def test_baseline_kept_when_no_model_is_better(registry: Engine) -> None:
    baseline = add(registry, "seasonal_naive", 0.30, baseline=True)
    tie = add(registry, "lstm", 0.30)  # equal is not better
    worse = add(registry, "gru", 0.45)
    choice = select_best(
        registry,
        "demand_forecasting",
        [tie, worse, baseline],
        metric="wape",
        higher_is_better=False,
    )
    assert choice.model_name == "seasonal_naive"
    assert choice.reason.startswith("no model beat the baseline seasonal_naive")


def test_higher_is_better_and_best_of_several_baselines(registry: Engine) -> None:
    ids = [
        add(
            registry, "logistic_regression", 0.60, baseline=True, metrics={"test": {"pr_auc": 0.6}}
        ),
        add(registry, "frequent", 0.70, baseline=True, metrics={"test": {"pr_auc": 0.7}}),
        add(registry, "dense", 0.65, metrics={"test": {"pr_auc": 0.65}}),
    ]
    choice = select_best(
        registry, "demand_forecasting", ids, metric="pr_auc", higher_is_better=True
    )
    assert choice.model_name == "frequent"  # the dense model beats one baseline, not the best


def test_new_selection_retires_the_old_one(registry: Engine) -> None:
    first = [add(registry, "naive", 0.5, baseline=True), add(registry, "lstm", 0.4)]
    select_best(registry, "demand_forecasting", first, metric="wape", higher_is_better=False)
    second = [
        add(registry, "naive", 0.5, baseline=True, version="v2"),
        add(registry, "gru", 0.3, version="v2"),
    ]
    select_best(registry, "demand_forecasting", second, metric="wape", higher_is_better=False)
    with Session(registry) as session:
        statuses = {
            (row.model_name, row.version): row.status
            for row in session.scalars(select(ModelVersion))
        }
    assert statuses[("lstm", "20261116-1200")] == ModelStatus.RETIRED
    assert statuses[("gru", "v2")] == ModelStatus.SELECTED
    assert list(statuses.values()).count(ModelStatus.SELECTED) == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"use_case": "weather"}, "unknown use case"),
        ({"metrics": {"validation": {"wape": 0.3}}}, "test metrics are required"),
        ({"metrics": {"train": {"wape": 0.3}, "test": {"wape": 0.3}}}, "unknown metric split"),
        ({"metrics": {"test": {"wape": float("nan")}}}, "not a finite number"),
        ({"metrics": {"test": {"wape": float("inf")}}}, "not a finite number"),
        ({"artifact_path": None}, "needs its saved .keras file"),
    ],
)
def test_register_refuses_bad_input(registry: Engine, changes: dict, message: str) -> None:
    with pytest.raises(RegistryError, match=message):
        add(registry, "lstm", 0.3, **changes)


def test_selection_errors(registry: Engine) -> None:
    lstm = add(registry, "lstm", 0.3)
    baseline = add(registry, "naive", 0.4, baseline=True, metrics={"test": {"mae": 1.0}})
    other = add(registry, "dense", 0.2, use_case="delay_prediction")
    cases = [
        ([], "no candidates"),
        ([lstm, 999], "do not exist"),
        ([lstm], "a baseline is needed"),
        ([lstm, other], "must belong to demand_forecasting"),
        ([lstm, baseline], "naive has no test wape"),
    ]
    for ids, message in cases:
        with pytest.raises(RegistryError, match=message):
            select_best(registry, "demand_forecasting", ids, metric="wape", higher_is_better=False)
    assert selected_model(registry, "demand_forecasting") is None


def test_same_model_version_cannot_be_registered_twice(registry: Engine) -> None:
    add(registry, "lstm", 0.3)
    with pytest.raises(IntegrityError):
        add(registry, "lstm", 0.3)


# ------------------------------------------------------------------ dataset access
def test_dataset_version_identifies_the_data(with_orders: Simulated, tmp_path: Path) -> None:
    _, engine, _ = with_orders
    path = tmp_path / "copy.db"
    shutil.copy(str(engine.url.database), path)
    copy = open_dataset(path)
    version = dataset_version(copy)
    assert version == dataset_version(engine)  # same data, same name
    assert version.startswith(
        f"orders{read_frame(copy, 'SELECT COUNT(*) AS n FROM orders').n[0]}-to"
    )
    first, last = history_range(copy)
    assert (last - first).days >= 700 and version.split("-to")[1].startswith(last.isoformat())
    with copy.begin() as connection:
        connection.exec_driver_sql("UPDATE orders SET customer_id = 1 WHERE id = 1")
    assert dataset_version(copy) != version  # any change, another name
    copy.dispose()


def test_read_frame_parses_dates(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    frame = read_frame(engine, "SELECT id, created_at FROM orders LIMIT 3", dates=("created_at",))
    assert str(frame["created_at"].dt.tz) == "UTC" and len(frame) == 3


def test_open_dataset_errors(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="generate_data.py"):
        open_dataset(tmp_path / "missing.db")
    empty = tmp_path / "empty.db"
    create_engine(sqlite_url(empty)).connect().close()
    with pytest.raises(DatasetError, match="not a warehouse database"):
        open_dataset(empty)


# ----------------------------------------------------------- TensorFlow and Keras
def tiny_model(seed: int):
    keras = keras_setup.keras
    keras_setup.set_seeds(seed)
    model = keras.Sequential(
        [keras.Input((4,)), keras.layers.Dense(8, activation="relu"), keras.layers.Dense(1)]
    )
    model.compile(optimizer=keras.optimizers.Adam(0.01), loss="mse")
    return model


def tiny_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(64, 4)).astype("float32")
    return x, (x @ np.array([1.0, -2.0, 0.5, 0.0], dtype="float32"))[:, None]


def test_build_train_one_step_save_and_load(tmp_path: Path) -> None:
    x, y = tiny_data()
    model = tiny_model(7)
    before = model.evaluate(x, y, verbose=0)
    model.fit(x, y, epochs=1, batch_size=64, verbose=0)  # one training step
    assert model.evaluate(x, y, verbose=0) < before
    path = keras_setup.save_model(model, tmp_path / "nested" / "tiny.keras")
    loaded = keras_setup.load_model(path)
    assert np.allclose(loaded.predict(x[:5], verbose=0), model.predict(x[:5], verbose=0))
    with pytest.raises(FileNotFoundError, match="train it first"):
        keras_setup.load_model(tmp_path / "missing.keras")


def test_same_seed_same_model() -> None:
    x, y = tiny_data()
    weights = []
    for seed in (7, 7, 8):
        model = tiny_model(seed)
        model.fit(x, y, epochs=2, batch_size=16, verbose=0)
        weights.append(model.get_weights()[0])
    assert np.array_equal(weights[0], weights[1])
    assert not np.array_equal(weights[0], weights[2])


def test_early_stopping_keeps_the_best_epoch(tmp_path: Path) -> None:
    x, y = tiny_data()
    model = tiny_model(7)
    checkpoint = tmp_path / "ckpt" / "best.keras"
    noise = np.random.default_rng(1).normal(size=y.shape).astype("float32") * 50
    history = model.fit(
        x[:48],
        y[:48],
        validation_data=(x[48:], noise[48:]),  # validation that cannot improve for long
        epochs=30,
        batch_size=16,
        verbose=0,
        callbacks=keras_setup.training_callbacks(checkpoint, patience=2),
    )
    losses = history.history["val_loss"]
    assert len(losses) < 30  # stopped early
    best = min(losses)
    assert model.evaluate(x[48:], noise[48:], verbose=0) == pytest.approx(best, rel=1e-4)
    assert checkpoint.exists()


def test_versions_and_artifact_paths() -> None:
    assert keras_setup.new_version(datetime(2026, 11, 16, 13, 28, tzinfo=UTC)) == "20261116-1328"
    path = keras_setup.artifact_path("demand_forecasting", "lstm", "20261116-1328")
    assert (
        keras_setup.relative_to_ml(path) == "artifacts/demand_forecasting/lstm/20261116-1328.keras"
    )
    assert keras_setup.relative_to_ml(Path("/elsewhere/x.keras")) == "/elsewhere/x.keras"
