"""Product recommendation: baskets and history without leakage, the baseline, ranking,
the networks and a full training run."""

import dataclasses
import shutil
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.models.ml import ModelStatus, ModelVersion
from baselines.recommendation import FrequentlyBoughtTogether
from data_generation.context import GenerationContext
from data_generation.database import sqlite_url
from feature_engineering.interaction_features import (
    MAX_CONTEXT,
    MAX_HISTORY,
    Baskets,
    every_target,
    held_out,
    load_baskets,
)
from training import keras_setup
from training.config import load_config
from training.data import read_frame

Simulated = tuple[GenerationContext, Engine, dict]


def toy(items: list[list[int]], customer: list[int] | None = None) -> Baskets:
    n = len(items)
    return Baskets(
        order_ids=np.arange(1, n + 1),
        customer=np.asarray(customer or [1] * n, "int32"),
        day=np.arange(n).astype("datetime64[D]"),
        items=[np.asarray(i) for i in items],
        history=np.zeros((n, MAX_HISTORY), "int32"),
        product_ids=np.arange(101, 106),
        categories=np.array([0, 1, 1, 2, 2, 3], "int32"),
        customers=2,
    )


# ---------------------------------------------------------------------- features
def test_baskets_and_history(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    baskets = load_baskets(engine)
    orders = read_frame(engine, "SELECT COUNT(*) AS n FROM orders").n[0]
    assert len(baskets.items) == orders and baskets.products == 50
    assert all(len(set(i)) == len(i) and i.min() >= 1 for i in baskets.items)
    assert len(baskets.categories) == 51 and baskets.categories[0] == 0
    # history = earlier orders of the same customer only, most recent last
    seen: dict[int, list[int]] = {}
    for row in range(len(baskets.items)):
        who = int(baskets.customer[row])
        expected = seen.get(who, [])[-MAX_HISTORY:]
        got = [int(i) for i in baskets.history[row] if i]
        assert got == expected
        seen.setdefault(who, []).extend(int(i) for i in baskets.items[row])
    assert (np.diff(baskets.day.astype("int64")) >= 0).all()


def test_training_examples_and_held_out_queries() -> None:
    baskets = toy([[1, 2, 3], [4], [2, 5]])
    examples = every_target(baskets)
    assert list(examples.target) == [1, 2, 3, 2, 5]  # single-product baskets skipped
    assert list(examples.context[0][:2]) == [2, 3] and examples.context.shape[1] == MAX_CONTEXT
    assert examples.context[3][0] == 5
    queries = held_out(baskets, seed=0)
    assert len(queries) == 2
    for context, target, items in zip(
        queries.context, queries.target, ([1, 2, 3], [2, 5]), strict=True
    ):
        assert target in items and set(context[context > 0]) == set(items) - {target}
    assert len(held_out(baskets, seed=0, limit=1)) == 1
    with pytest.raises(ValueError, match="two or more"):
        every_target(toy([[1], [2]]))


# ---------------------------------------------------------------------- baseline
def test_frequently_bought_together_by_hand() -> None:
    fbt = FrequentlyBoughtTogether().fit(toy([[1, 2], [1, 2], [1, 3], [4, 5]]))
    assert fbt.co[1, 2] == 2 and fbt.co[1, 3] == 1 and fbt.co[1, 1] == 0
    context = np.zeros((1, MAX_CONTEXT), "int32")
    context[0, 0] = 1
    scores = fbt.scores({"context": context})[0]
    assert scores[2] > scores[3] > scores[4] and scores[4] > scores[0]  # popularity tie-break


def test_top_k_and_evaluation() -> None:
    from feature_engineering.interaction_features import Queries
    from training.train_recommendation import evaluate, top_k

    scores = np.array([[9.0, 8.0, 7.0, 6.0, 5.0, 4.0]] * 2)
    context = np.zeros((2, MAX_CONTEXT), "int32")
    context[0, 0] = 1  # product 1 already in the basket
    top = top_k(scores, context, k=2)
    assert top == [[2, 3], [1, 2]]  # never padding (0) or the basket's products
    q = Queries(
        context, np.ones(2, "int32"), np.zeros((2, MAX_HISTORY), "int32"), np.array([2, 5], "int32")
    )
    result = evaluate(scores, q, products=5)
    assert result["hit_rate_at_10"] == 1.0  # both targets in the top 10 of 5 products
    assert result["ndcg_at_10"] == pytest.approx((1 + 1 / np.log2(6)) / 2)  # ranks 1 and 5


def test_negative_sampling() -> None:
    from training.train_recommendation import negatives

    queries = every_target(toy([[1, 2, 3], [2, 5]]))
    x, y = negatives(queries, products=5, per_positive=3, seed=0)
    assert len(y) == len(queries) * 4 and y.reshape(-1, 4)[:, 0].tolist() == [1] * len(queries)
    candidates = x["candidate"].reshape(-1, 4)
    assert (candidates[:, 0] == queries.target).all()
    assert (candidates[:, 1:] != queries.target[:, None]).all()  # negatives never the positive
    assert ((candidates >= 1) & (candidates <= 5)).all()


# ---------------------------------------------------------------------- networks
@pytest.mark.parametrize("name", ["ncf", "two_tower", "deep_cross", "gru_sequential"])
def test_networks_build_train_score_and_reload(name: str, tmp_path: Path) -> None:
    from models.recommendation import ARCHITECTURES, TRAINING
    from models.recommendation.common import score_pointwise
    from training.train_recommendation import negatives

    baskets = toy([[1, 2, 3], [2, 5], [1, 4], [3, 4, 5]], customer=[1, 2, 1, 2])
    queries = every_target(baskets)
    shapes = {"products": 5, "customers": 2, "categories": baskets.categories.tolist()}
    keras_setup.set_seeds(5)
    model = ARCHITECTURES[name](shapes, {"embedding": 4, "units": [8], "hidden": 8, "dim": 4}, 0.01)
    if TRAINING[name] == "softmax":
        model.fit(queries.inputs(), queries.target, epochs=1, verbose=0)
        scores = model.predict(queries.inputs(), verbose=0)
    else:
        x, y = negatives(queries, 5, 2, seed=0)
        model.fit(x, y, epochs=1, verbose=0)
        scores = score_pointwise(model, queries.inputs(), 5, chunk=3)
    assert scores.shape == (len(queries), 6)
    path = keras_setup.save_model(model, tmp_path / f"{name}.keras")
    again = keras_setup.load_model(path)
    if TRAINING[name] == "softmax":
        assert np.allclose(again.predict(queries.inputs(), verbose=0), scores, atol=1e-5)
    else:
        assert np.allclose(
            score_pointwise(again, queries.inputs(), 5)[:, 1:], scores[:, 1:], atol=1e-5
        )


def test_masked_mean_ignores_padding() -> None:
    from models.recommendation.common import MaskedMean

    ids = np.array([[3, 0, 0]])
    vectors = np.array([[[2.0, 4.0], [100.0, 100.0], [100.0, 100.0]]], "float32")
    assert np.allclose(MaskedMean()([ids, vectors]).numpy(), [[2.0, 4.0]])


# ------------------------------------------------------------------ training run
def test_training_run(with_orders: Simulated, tmp_path: Path, monkeypatch) -> None:
    from training import train_recommendation

    _, engine, _ = with_orders
    database = tmp_path / "train.db"
    shutil.copy(str(engine.url.database), database)
    monkeypatch.setattr(keras_setup, "ARTIFACT_DIR", tmp_path / "artifacts")
    base = load_config("recommendation")
    config = dataclasses.replace(
        base,
        max_epochs=2,
        features={**base.features, "eval_queries": 50},
        models={"two_tower": {"embedding": 4, "hidden": 8, "dim": 4}},
    )
    report = tmp_path / "report.md"
    outcome = train_recommendation.run(
        database, config=config, report=lambda _: None, write_report=report
    )
    assert [r.name for r in outcome.results] == ["frequently_bought_together", "two_tower"]
    for result in outcome.results:
        assert 0 <= result.test["ndcg_at_10"] <= result.test["hit_rate_at_10"] <= 1
        assert 0 < result.test["coverage"] <= 1
    basket, top, hidden = outcome.example
    assert len(top) == 10 and not set(basket) & set(top)  # never recommends the basket
    with Session(create_engine(sqlite_url(database))) as session:
        rows = session.scalars(
            select(ModelVersion).where(ModelVersion.use_case == "recommendation")
        ).all()
    assert len(rows) == 2 and sum(r.status == ModelStatus.SELECTED for r in rows) == 1
    text = report.read_text()
    assert "| Model | Type | ndcg_at_10" in text and "## Example" in text
