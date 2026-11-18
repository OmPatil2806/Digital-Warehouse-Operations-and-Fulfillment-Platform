"""Train and compare product recommenders (use case 6).

On baskets of the validation and test periods, one product is held out of each basket;
every method ranks the whole catalogue for the rest (basket so far, customer and their
earlier purchases), never recommending what is already in the basket. Metrics at K=10:
Precision@K, Recall@K, Hit Rate@K, NDCG@K (selection, higher is better) and catalogue
coverage. The frequently-bought-together baseline and the networks in
configs/recommendation.yaml all answer exactly the same queries.

Run from ml/:  python -m training.train_recommendation [--database PATH]
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from baselines.recommendation import FrequentlyBoughtTogether
from data_generation.database import DEFAULT_DATABASE, upgrade_database
from evaluation import metrics
from feature_engineering.interaction_features import (
    Baskets,
    Queries,
    every_target,
    held_out,
    load_baskets,
)
from registry.register_model import Selection
from training import keras_setup
from training.config import ExperimentConfig, load_config
from training.data import dataset_version, history_range, open_dataset
from training.experiment import ModelResult, Reporter, register_results, timer
from training.splits import TEST, TRAIN, VALIDATION, chronological_split

USE_CASE = "recommendation"
K = 10
SELECTION_METRIC = f"ndcg_at_{K}"  # higher is better
REPORT = Path(__file__).resolve().parents[1] / "evaluation" / "reports" / f"{USE_CASE}.md"
FEATURES = ["basket_products", "customer", "purchase_history"]


@dataclass
class RecommendationRun:
    version: str
    dataset_version: str
    split_description: str
    sizes: dict[str, int]
    results: list[ModelResult]
    selection: Selection
    example: tuple[list[int], list[int], int] | None  # basket, top 10, held-out (product ids)


def top_k(scores: np.ndarray, context: np.ndarray, k: int = K) -> list[list[int]]:
    """The k best products per query, never padding or products already in the basket
    (fewer than k when the catalogue is smaller)."""
    masked = scores.astype("float64").copy()
    masked[:, 0] = -np.inf
    rows = np.repeat(np.arange(len(context)), context.shape[1])
    masked[rows, context.ravel()] = -np.inf  # context 0 = padding, already -inf
    k = min(k, masked.shape[1] - 1)
    part = np.argpartition(-masked, k - 1, axis=1)[:, :k]
    order = np.argsort(-np.take_along_axis(masked, part, axis=1), axis=1, kind="stable")
    best = np.take_along_axis(part, order, axis=1)
    return [[int(i) for i in row if np.isfinite(masked[r, i])] for r, row in enumerate(best)]


def evaluate(scores: np.ndarray, queries: Queries, products: int) -> dict[str, float]:
    recommended = top_k(scores, queries.context)
    return metrics.ranking_metrics(
        recommended, [{int(t)} for t in queries.target], catalogue_size=products, k=K
    )


def negatives(queries: Queries, products: int, per_positive: int, seed: int):
    """Pointwise training rows: the held-out product (label 1) and random others (0)."""
    rng = np.random.default_rng(seed)
    n = len(queries)
    sampled = rng.integers(1, products + 1, size=(n, per_positive))
    clash = sampled == queries.target[:, None]
    sampled[clash] = sampled[clash] % products + 1  # never the positive itself
    candidates = np.concatenate([queries.target[:, None], sampled], axis=1).ravel()
    rows = np.repeat(np.arange(n), per_positive + 1)
    labels = np.tile(np.r_[1.0, np.zeros(per_positive)], n).astype("float32")
    inputs = {k: v[rows] for k, v in queries.inputs().items()}
    return {**inputs, "candidate": candidates.astype("int32")}, labels


def run(
    database: Path = DEFAULT_DATABASE,
    *,
    models: Sequence[str] | None = None,
    config: ExperimentConfig | None = None,
    report: Reporter = print,
    write_report: Path | None = REPORT,
) -> RecommendationRun:
    from models.recommendation import ARCHITECTURES, TRAINING
    from models.recommendation.common import score_pointwise

    config = config or load_config(USE_CASE)
    names = list(config.models) if models is None else list(models)
    unknown = [n for n in names if n not in config.models]
    if unknown:
        raise ValueError(f"unknown model(s) {unknown}; configured: {list(config.models)}")
    engine = open_dataset(database)
    upgrade_database(database)
    version, data_version = keras_setup.new_version(), dataset_version(engine)
    first, last = history_range(engine)
    report(f"Product recommendation on {data_version}")
    baskets = load_baskets(engine)
    split = chronological_split(
        first, last, validation_days=config.validation_days, test_days=config.test_days
    )
    periods = split.assign(baskets.day.astype(object))
    parts: dict[str, Baskets] = {
        name: baskets.subset(np.flatnonzero(periods == name)) for name in (TRAIN, VALIDATION, TEST)
    }
    settings = config.features
    train_q = every_target(parts[TRAIN])
    limit = int(settings.get("max_train_examples", 0))
    if limit and len(train_q) > limit:
        rng = np.random.default_rng(config.seed)
        train_q = train_q.subset(np.sort(rng.choice(len(train_q), limit, replace=False)))
    eval_q = {
        VALIDATION: held_out(
            parts[VALIDATION], config.seed + 1, int(settings.get("eval_queries", 3000))
        ),
        TEST: held_out(parts[TEST], config.seed + 2, int(settings.get("eval_queries", 3000))),
    }
    products = baskets.products
    report(f"  {split.describe()}")
    report(
        f"  {len(train_q):,} training examples; {len(eval_q[VALIDATION]):,} validation and "
        f"{len(eval_q[TEST]):,} test queries; {products:,} products"
    )

    with timer() as elapsed:
        fbt = FrequentlyBoughtTogether().fit(parts[TRAIN])
        scorers = {"frequently_bought_together": lambda q: fbt.scores(q.inputs())}
        scored = {p: evaluate(fbt.scores(q.inputs()), q, products) for p, q in eval_q.items()}
        results = [
            ModelResult("frequently_bought_together", True, scored[VALIDATION], scored[TEST], 0)
        ]
        results[0].seconds = elapsed()
    report(
        f"  {'frequently_bought_together':<28} test NDCG@10 "
        f"{scored[TEST][SELECTION_METRIC]:.3f} (baseline)"
    )

    shapes = {
        "products": products,
        "customers": baskets.customers,
        "categories": baskets.categories.tolist(),
    }
    per_negative = int(settings.get("negatives", 4))
    for name in names:
        with timer() as elapsed:
            keras_setup.set_seeds(config.seed)
            model = ARCHITECTURES[name](shapes, config.model(name), config.learning_rate)
            artifact = keras_setup.artifact_path(USE_CASE, name, version)
            checkpoint = artifact.with_suffix(".checkpoint.keras")
            valid_train = every_target(parts[VALIDATION])
            if TRAINING[name] == "softmax":
                x, y = train_q.inputs(), train_q.target
                vx, vy = valid_train.inputs(), valid_train.target
            else:
                x, y = negatives(train_q, products, per_negative, config.seed)
                vx, vy = negatives(valid_train, products, per_negative, config.seed + 1)
            fit = model.fit(
                x,
                y,
                validation_data=(vx, vy),
                epochs=config.max_epochs,
                batch_size=config.batch_size,
                verbose=0,
                callbacks=keras_setup.training_callbacks(checkpoint, patience=config.patience),
            )
            keras_setup.save_model(model, artifact)
            checkpoint.unlink(missing_ok=True)

            def scores_of(q: Queries, model=model, kind=TRAINING[name]) -> np.ndarray:
                if kind == "softmax":
                    return model.predict(q.inputs(), batch_size=4096, verbose=0)
                return score_pointwise(model, q.inputs(), products)

            scorers[name] = scores_of
            scored = {p: evaluate(scores_of(q), q, products) for p, q in eval_q.items()}
            result = ModelResult(
                name,
                False,
                scored[VALIDATION],
                scored[TEST],
                0,
                params=config.model(name),
                artifact=artifact,
                epochs=len(fit.history["loss"]),
            )
            result.seconds = elapsed()
        results.append(result)
        report(
            f"  {name:<28} test NDCG@10 {result.test[SELECTION_METRIC]:.3f} "
            f"({result.epochs} epochs, {result.seconds:.0f}s)"
        )

    selection = register_results(
        engine,
        results,
        use_case=USE_CASE,
        version=version,
        dataset_version=data_version,
        features=FEATURES,
        common_params={**settings, "k": K, "seed": config.seed},
        metric=SELECTION_METRIC,
        higher_is_better=True,
    )
    report(f"Selected: {selection.reason}")
    engine.dispose()

    # One test basket answered by the selected method (product ids).
    q = eval_q[TEST].subset(np.array([0]))
    top = top_k(scorers[selection.model_name](q), q.context)[0]
    ids = baskets.product_ids
    example = (
        [int(ids[i - 1]) for i in q.context[0] if i],
        [int(ids[i - 1]) for i in top],
        int(ids[q.target[0] - 1]),
    )
    outcome = RecommendationRun(
        version,
        data_version,
        split.describe(),
        {"train_examples": len(train_q), **{p: len(q) for p, q in eval_q.items()}},
        results,
        selection,
        example,
    )
    if write_report is not None:
        write_report.parent.mkdir(parents=True, exist_ok=True)
        write_report.write_text(markdown_report(outcome), encoding="utf-8")
        report(f"Report: {write_report}")
    return outcome


def markdown_report(outcome: RecommendationRun) -> str:
    columns = [
        f"ndcg_at_{K}",
        f"hit_rate_at_{K}",
        f"recall_at_{K}",
        f"precision_at_{K}",
        "coverage",
    ]
    lines = [
        "# Product recommendation: model comparison",
        "",
        f"- Dataset: `{outcome.dataset_version}`, training run `{outcome.version}`",
        f"- Split by order day: {outcome.split_description}",
        f"- {outcome.sizes['train_examples']:,} training examples; "
        f"{outcome.sizes[TEST]:,} test queries: one product held out of each test-period "
        "basket with two or more products; every method ranks the whole catalogue for the "
        "rest of the basket, the customer and their earlier purchases.",
        f"- Metrics on the **test** queries at K={K}: with one held-out product, Hit Rate@{K} "
        f"= Recall@{K} (share of queries where it is in the top {K}); `ndcg_at_{K}` (used for "
        "the selection) also rewards ranking it higher; `coverage`: share of the catalogue "
        "that appears in any top-10 list.",
        "",
        "| Model | Type | " + " | ".join(columns) + " | Epochs | Time |",
        "|---|---|" + "---:|" * (len(columns) + 2),
    ]
    for r in sorted(outcome.results, key=lambda r: -r.test[SELECTION_METRIC]):
        name = f"**{r.name}** (selected)" if r.name == outcome.selection.model_name else r.name
        kind = "baseline" if r.is_baseline else "Keras"
        values = " | ".join(f"{r.test[c]:.3f}" for c in columns)
        lines.append(f"| {name} | {kind} | {values} | {r.epochs or '-'} | {r.seconds:.0f} s |")
    lines += ["", f"**Selection:** {outcome.selection.reason}."]
    if outcome.example:
        basket, top, hidden = outcome.example
        place = f"rank {top.index(hidden) + 1}" if hidden in top else "not in the top 10"
        lines += [
            "",
            "## Example (first test query, selected method)",
            "",
            f"- In the basket: products {', '.join(map(str, basket))}",
            f"- Top {K} recommended: {', '.join(map(str, top))}",
            f"- Held-out product: {hidden} ({place})",
        ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and compare product recommenders.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--models", nargs="+", help="networks to train (default: all)")
    args = parser.parse_args(argv)
    run(args.database, models=args.models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
