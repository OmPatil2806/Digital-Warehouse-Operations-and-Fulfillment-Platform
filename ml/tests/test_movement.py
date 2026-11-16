"""Movement classification: features, ABC, clustering layers and methods, evaluation."""

import dataclasses
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.models.ml import ModelStatus, ModelVersion
from baselines.movement import abc_classes
from data_generation.context import GenerationContext
from data_generation.database import sqlite_url
from evaluation import metrics
from feature_engineering.movement_features import (
    FEATURES,
    Movement,
    build_movement,
    movement_features,
    order_classes,
    picks_per_day,
)
from training import keras_setup
from training.config import load_config
from training.data import history_range, read_frame

Simulated = tuple[GenerationContext, Engine, dict]


def toy(lines: np.ndarray, units: np.ndarray) -> Movement:
    return Movement(np.arange(1, len(lines) + 1), date(2026, 1, 1), lines, units)


def test_movement_matches_the_order_lines(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    movement = build_movement(engine, *history_range(engine))
    totals = read_frame(engine, "SELECT COUNT(*) AS n, SUM(quantity) AS u FROM order_items")
    assert movement.lines.sum() == totals.n[0] and movement.units.sum() == totals.u[0]
    frame = movement_features(movement, 0, movement.days - 1)
    assert list(frame.columns) == list(FEATURES) and len(frame) == len(movement.product_ids)


def test_features_by_hand() -> None:
    days = 28
    lines = np.zeros((2, days))
    units = np.zeros((2, days))
    lines[0], units[0] = 1, 2  # every day: 1 pick of 2 units
    lines[1, [0, 14]], units[1, [0, 14]] = 1, [3, 3]  # twice, 14 days apart
    f = movement_features(toy(lines, units), 0, days - 1)
    assert f.loc[0, "log_lines_per_day"] == pytest.approx(np.log1p(1))
    assert f.loc[0, "sale_day_share"] == 1 and f.loc[0, "log_cv_daily"] == 0
    assert f.loc[0, "log_units_per_line"] == pytest.approx(np.log1p(2))
    assert f.loc[0, "log_mean_gap_days"] == pytest.approx(np.log1p(1))
    assert f.loc[0, "trend"] == pytest.approx(0)
    assert f.loc[1, "sale_day_share"] == pytest.approx(2 / 28)
    assert f.loc[1, "log_mean_gap_days"] == pytest.approx(np.log1p(27))  # (28-1)/(2-1)
    assert f.loc[1, "log_units_per_line"] == pytest.approx(np.log1p(3))
    assert list(picks_per_day(toy(lines, units), 0, 13)) == pytest.approx([1, 1 / 14])
    with pytest.raises(ValueError, match="21 days"):
        movement_features(toy(lines, units), 0, 10)
    with pytest.raises(ValueError, match="outside"):
        movement_features(toy(lines, units), 0, 40)


def test_abc_by_hand() -> None:
    # shares before each product: 0, 0.5, 0.8, 0.9, 0.95 -> A, A, B, B, C
    assert list(abc_classes(np.array([5, 50, 10, 30, 5]))) == [1, 2, 1, 2, 0]
    assert list(abc_classes(np.zeros(3))) == [0, 0, 0]
    with pytest.raises(ValueError):
        abc_classes(np.array([]))


def test_order_classes_by_activity() -> None:
    labels = np.array([7, 7, 3, 3, 5])
    activity = np.array([9.0, 8.0, 0.1, 0.2, 4.0])
    assert list(order_classes(labels, activity)) == [2, 2, 0, 0, 1]
    assert list(order_classes(np.array([1, 1, 0]), np.array([5.0, 5.0, 1.0]))) == [2, 2, 1]


# ------------------------------------------------------------------------- models
def test_cluster_assignment_and_target_distribution() -> None:
    from models.movement_classification.common import ClusterAssignment
    from models.movement_classification.dec import target_distribution

    layer = ClusterAssignment(2)
    layer.build((None, 1))
    layer.centres.assign(np.array([[0.0], [10.0]], "float32"))
    q = layer(np.array([[0.0], [9.0]], "float32")).numpy()
    assert np.allclose(q.sum(axis=1), 1) and q[0, 0] > 0.9 and q[1, 1] > 0.9
    # by hand for z = 0: 1/(1+0) = 1 and 1/(1+100) -> normalised
    assert q[0, 0] == pytest.approx(1 / (1 + 1 / 101))
    p = target_distribution(np.array([[0.6, 0.4], [0.5, 0.5]]))
    # f = (1.1, 0.9): weights 0.36/1.1, 0.16/0.9 -> normalised row
    first = np.array([0.36 / 1.1, 0.16 / 0.9])
    assert p[0] == pytest.approx(first / first.sum()) and p[0, 0] > 0.6  # sharper


@pytest.mark.parametrize("name", ["autoencoder_kmeans", "vae_kmeans", "dec"])
def test_methods_find_clear_groups_and_reload(name: str, tmp_path: Path) -> None:
    from models.movement_classification import METHODS

    rng = np.random.default_rng(0)
    centres = np.array([[0, 0, 0], [6, 6, 0], [0, 6, 6]], float)
    truth = np.repeat([0, 1, 2], 40)
    raw = (centres[truth] + rng.normal(scale=0.3, size=(120, 3))).astype("float32")
    mean, variance = raw.mean(axis=0), raw.var(axis=0)
    params = {"hidden": [8], "latent": 2, "epochs": 60, "pretrain_epochs": 60, "rounds": 3}
    clusterer = METHODS[name]((raw - mean) / np.sqrt(variance), params, 1, mean, variance)
    labels = clusterer.labels(raw)  # raw features in: normalisation is inside the model
    assert metrics.cluster_stability([labels, truth]) > 0.9
    path = keras_setup.save_model(clusterer.model, tmp_path / f"{name}.keras")
    again = keras_setup.load_model(path).predict(raw, verbose=0)
    assert np.allclose(again, clusterer.probabilities(raw), atol=1e-5)


# --------------------------------------------------------------------- evaluation
def test_evaluation_rules() -> None:
    from training.train_movement import evaluate

    x = np.array([[0.0], [0.1], [5.0], [5.1], [10.0], [10.1]])
    classes = np.array([0, 0, 1, 1, 2, 2])
    picks = np.array([0.1, 0.1, 1.0, 1.0, 10.0, 10.0])
    good = evaluate(classes, x, picks, classes, stability=1.0)
    assert good["order_ok"] == 1 and good["persistence"] == 1
    assert good["fast_pick_share"] == pytest.approx(20 / 22.2)
    assert (
        good["selection_score"] == pytest.approx(good["silhouette"]) and good["share_fast"] == 1 / 3
    )
    assert evaluate(classes, x, picks, classes, stability=0.5)["selection_score"] == -1
    swapped = evaluate(classes, x, picks[::-1], classes, stability=1.0)
    assert swapped["order_ok"] == 0 and swapped["selection_score"] == -1
    weak_fast = evaluate(classes, x, np.array([0.1, 0.1, 9, 9, 1, 1]), classes, stability=1.0)
    assert weak_fast["selection_score"] == -1  # fast class carries few picks


def test_training_run(with_orders: Simulated, tmp_path: Path, monkeypatch) -> None:
    from training import train_movement

    _, engine, _ = with_orders
    database = tmp_path / "train.db"
    shutil.copy(str(engine.url.database), database)
    monkeypatch.setattr(keras_setup, "ARTIFACT_DIR", tmp_path / "artifacts")
    base = load_config("movement_classification")
    config = dataclasses.replace(
        base,
        features={**base.features, "stability_runs": 2},
        models={"autoencoder_kmeans": {"hidden": [4], "latent": 2, "epochs": 5}},
    )
    report = tmp_path / "report.md"
    outcome = train_movement.run(
        database, config=config, report=lambda _: None, write_report=report
    )
    assert [r.name for r in outcome.results] == ["abc", "autoencoder_kmeans"]
    learned = outcome.results[1]
    assert learned.artifact.exists() and 0 <= learned.test["stability"] <= 1
    assert set(learned.params["class_of_cluster"].values()) <= {"slow", "medium", "fast"}
    assert outcome.results[0].test["stability"] == 1.0
    with Session(create_engine(sqlite_url(database))) as session:
        rows = session.scalars(
            select(ModelVersion).where(ModelVersion.use_case == "movement_classification")
        ).all()
    assert len(rows) == 2 and sum(r.status == ModelStatus.SELECTED for r in rows) == 1
    assert rows[0].features == base.features["columns"]
    assert "| Method | Type | selection_score" in report.read_text()


def test_unknown_feature_column(with_orders: Simulated) -> None:
    from training import train_movement

    _, engine, _ = with_orders
    config = dataclasses.replace(
        load_config("movement_classification"), features={"columns": ["colour"]}
    )
    with pytest.raises(ValueError, match="unknown movement features"):
        train_movement.run(Path(str(engine.url.database)), config=config, write_report=None)
