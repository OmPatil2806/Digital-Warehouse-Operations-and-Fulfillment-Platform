"""Slotting: layout data, pick-time model, the constrained optimizer, the networks and a
full training run."""

import dataclasses
import shutil
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.models.ml import ModelStatus, ModelVersion
from baselines.slotting import abc_cost
from data_generation.context import GenerationContext
from data_generation.database import sqlite_url
from feature_engineering.slotting_features import (
    STORAGE_TYPES,
    ZONE_TYPES,
    Layout,
    face_need,
    load_layout,
    pair_features,
    pick_seconds,
    product_state,
)
from models.slotting.optimizer import Assignment, assign, violations
from training import keras_setup
from training.config import load_config

Simulated = tuple[GenerationContext, Engine, dict]
PICKING, BULK, COLD = (ZONE_TYPES.index(z) for z in ("picking", "bulk", "cold"))


def toy_layout() -> Layout:
    """Three products (general light, general heavy, cold) and five bins in one warehouse."""
    return Layout(
        product_ids=np.array([1, 2, 3]),
        weight_kg=np.array([1.0, 20.0, 2.0]),
        volume_cm3=np.array([1000.0, 5000.0, 1000.0]),
        category=np.zeros(3, int),
        category_names=["Only"],
        storage=np.array([0, 0, STORAGE_TYPES.index("cold")]),
        bin_ids=np.arange(10, 15),
        bin_warehouse=np.ones(5, int),
        bin_zone=np.array([PICKING, PICKING, BULK, COLD, -1]),  # last: returns zone
        bin_level=np.array([3, 1, 1, 1, 1]),
        bin_distance=np.array([5.0, 10.0, 30.0, 40.0, 1.0]),
        bin_max_kg=np.array([30.0, 30.0, 500.0, 50.0, 500.0]),
        bin_max_cm3=np.array([10_000.0, 10_000.0, 1e6, 10_000.0, 1e6]),
        warehouse_ids=np.array([1]),
    )


# ---------------------------------------------------------------------- features
def test_layout_from_the_database(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    layout = load_layout(engine)
    assert len(layout.product_ids) == 50 and len(layout.bin_ids) == 300
    assert set(np.unique(layout.bin_zone)) <= {-1, 0, 1, 2, 3}
    names = np.array(layout.category_names)[layout.category]
    cold = names[layout.storage == STORAGE_TYPES.index("cold")]
    assert set(cold) <= {"Food & Beverages"}  # derived from where deliveries went
    assert (layout.weight_kg > 0).all() and (layout.bin_distance > 0).all()


def test_pick_seconds_by_hand() -> None:
    layout = toy_layout()
    # bin 0: 2 x 5 m / 1.2 + 15 + 4 x 2 units, level 3 -> + 0.5 x 1 kg x 1
    assert pick_seconds(layout, np.array([0]), np.array([0]), 2.0)[0] == pytest.approx(
        10 / 1.2 + 15 + 8 + 0.5
    )
    # heavy product (20 kg) on level 3 costs 10 s more than on level 1 at the same distance
    high = pick_seconds(layout, np.array([1]), np.array([0]), 1.0)[0]
    assert high - (10 / 1.2 + 19) == pytest.approx(10.0)
    layout.bin_level[0] = 4
    assert pick_seconds(layout, np.array([0]), np.array([0]), 1.0)[0] == pytest.approx(
        10 / 1.2 + 19 + 1.0 + 3.0  # two levels above 2 and the step ladder
    )


def test_face_need() -> None:
    layout = toy_layout()
    kg, cm3 = face_need(layout, np.array([0.0, 1.0, 0.3]), np.array([0, 1, 2]))
    assert list(kg) == pytest.approx([1.0, 20.0 * 7, 2.0 * 3])  # at least one unit
    assert cm3[1] == pytest.approx(35_000)  # 7 heavy units fit only the bulk bin
    kg, _ = face_need(layout, np.array([10.0]), np.array([2]))  # 70 cold units: cap
    assert kg[0] == pytest.approx(2.0 * 10)  # 10 units fit the cold bin (10,000 cm³)


def test_product_state_by_hand() -> None:
    lines = np.zeros((1, 2, 100))
    units = np.zeros((1, 2, 100))
    lines[0, 0, 72:100] = 1  # last 28 days: one pick a day of 3 units
    units[0, 0, 72:100] = 3
    state = product_state(lines, units, 99)
    assert state.picks_28[0, 0] == 1 and state.picks_90[0, 0] == pytest.approx(28 / 90)
    assert state.units_per_pick[0, 0] == 3 and state.units_per_pick[0, 1] == 1
    assert state.season[0, 0] == 1  # no last year yet
    with pytest.raises(ValueError, match="90 days"):
        product_state(lines, units, 50)


def test_pair_features() -> None:
    layout = toy_layout()
    lines = np.ones((1, 3, 100))
    state = product_state(lines, lines, 99)
    x = pair_features(layout, state, 0, np.array([0, 1]), np.array([0, 2]))
    assert x["product"].shape == (2, 8) and x["bin"].shape == (2, 4)
    assert x["categorical"].sum(axis=1).tolist() == [2, 2] and x["wide"].sum(axis=1).tolist() == [
        2,
        2,
    ]
    assert x["bin"][1, 0] == 30.0 and x["product"][1, 7] == 1  # distance, heavy flag


# --------------------------------------------------------------------- optimizer
def test_optimizer_respects_zones_and_capacity() -> None:
    layout = toy_layout()
    products = np.array([0, 1, 2])
    need_kg, need_cm3 = np.array([1.0, 20.0, 2.0]), np.array([1000.0, 5000.0, 1000.0])

    def distance_cost(p: np.ndarray, b: np.ndarray) -> np.ndarray:
        return layout.bin_distance[b] * (1 + p)

    plan = assign(layout, 0, products, distance_cost, need_kg, need_cm3)
    bins = plan.as_dict()
    assert bins[2] == 3  # cold product: only the cold bin, however far
    assert 4 not in bins.values()  # never the returns zone, though it is nearest
    assert bins[1] == 0 and bins[0] == 0  # both fit the nearest picking bin
    assert violations(layout, plan) == {"zone": 0, "overweight": 0, "overvolume": 0, "unplaced": 0}

    # tighter capacity: only one product fits a picking bin; the bigger saver goes first
    layout.bin_max_kg[:2] = 20.0
    plan = assign(layout, 0, products[:2], distance_cost, need_kg[:2], need_cm3[:2])
    assert plan.as_dict() == {1: 0, 0: 1}
    assert violations(layout, plan)["overweight"] == 0
    # too bulky for any picking bin: goes to the bulk bin though it is farther
    plan = assign(layout, 0, np.array([1]), distance_cost, np.array([1.0]), np.array([50_000.0]))
    assert plan.as_dict() == {1: 2}


def test_unplaced_and_broken_layouts_are_reported() -> None:
    layout = toy_layout()
    plan = assign(
        layout,
        0,
        np.array([2]),
        lambda p, b: layout.bin_distance[b],
        np.array([999.0]),
        np.array([1.0]),
    )
    assert list(plan.bins) == [-1] and violations(layout, plan)["unplaced"] == 1
    bad = Assignment(
        0,
        np.array([2, 0, 1]),
        np.array([0, 4, 1]),
        np.array([1.0, 1.0, 40.0]),
        np.array([1.0, 1.0, 20_000.0]),
    )
    found = violations(layout, bad)
    assert found["zone"] == 2  # cold product in a picking bin, a product in returns
    assert found["overweight"] == 1  # 40 kg in a 30 kg bin
    assert found["overvolume"] == 1  # 20,000 cm³ in a 10,000 cm³ bin


def test_abc_cost_prefers_near_bins_for_fast_movers() -> None:
    layout = toy_layout()
    cost = abc_cost(layout, np.array([5.0, 0.1, 1.0]))
    assert cost(np.array([0]), np.array([0]))[0] < cost(np.array([0]), np.array([1]))[0]
    assert cost(np.array([0]), np.array([1]))[0] > cost(np.array([1]), np.array([1]))[0]


# ---------------------------------------------------------------------- networks
@pytest.mark.parametrize("name", ["dense_suitability", "wide_deep_suitability"])
def test_networks_build_train_and_reload(name: str, tmp_path: Path) -> None:
    from models.slotting import ARCHITECTURES

    rng = np.random.default_rng(0)
    x = {
        "product": rng.normal(size=(64, 8)).astype("float32"),
        "bin": rng.normal(size=(64, 4)).astype("float32"),
        "categorical": np.eye(6, dtype="float32")[rng.integers(0, 6, 64)],
        "wide": np.eye(5, dtype="float32")[rng.integers(0, 5, 64)],
    }
    y = (x["product"][:, 0] + x["bin"][:, 0]).astype("float32")
    keras_setup.set_seeds(2)
    model = ARCHITECTURES[name]({k: v.shape[1:] for k, v in x.items()}, {"units": [8]}, 0.01, x)
    own = {t.name: x[t.name] for t in model.inputs}
    model.fit(own, y, epochs=1, batch_size=64, verbose=0)
    out = model.predict(own, verbose=0)
    path = keras_setup.save_model(model, tmp_path / f"{name}.keras")
    assert np.allclose(keras_setup.load_model(path).predict(own, verbose=0), out, atol=1e-5)


# ------------------------------------------------------------------ training run
def test_training_run(with_orders: Simulated, tmp_path: Path, monkeypatch) -> None:
    from training import train_slotting

    _, engine, _ = with_orders
    database = tmp_path / "train.db"
    shutil.copy(str(engine.url.database), database)
    monkeypatch.setattr(keras_setup, "ARTIFACT_DIR", tmp_path / "artifacts")
    base = load_config("slotting")
    config = dataclasses.replace(
        base,
        max_epochs=2,
        features={**base.features, "snapshot_every": 56, "bins_per_product": 4},
        models={"dense_suitability": {"units": [8]}},
    )
    report = tmp_path / "report.md"
    outcome = train_slotting.run(
        database, config=config, report=lambda _: None, write_report=report
    )
    assert [r.name for r in outcome.results] == ["abc_slotting", "dense_suitability"]
    for result in outcome.results:
        assert result.test["violations"] == 0  # hard rules hold for every method
        assert result.test["selection_score"] == pytest.approx(result.test["pick_time_reduction"])
        assert 0 < result.test["bins_used_share"] <= 1
    assert outcome.oracle["test"]["violations"] == 0
    best = max(r.test["pick_time_reduction"] for r in outcome.results)
    assert outcome.oracle["test"]["pick_time_reduction"] >= best - 1e-9  # the upper bound
    with Session(create_engine(sqlite_url(database))) as session:
        rows = session.scalars(
            select(ModelVersion).where(ModelVersion.use_case == "slotting")
        ).all()
    assert len(rows) == 2 and sum(r.status == ModelStatus.SELECTED for r in rows) == 1
    text = report.read_text()
    assert "current layout | reference" in text and "perfect foresight" in text
