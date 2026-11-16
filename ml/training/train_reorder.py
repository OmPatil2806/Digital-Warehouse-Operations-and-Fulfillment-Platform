"""Train and compare stockout-risk models for reorder recommendations (use case 2).

The reorder-point baseline and the networks in configs/reorder.yaml (Dense, Wide &
Deep, LSTM) score every in-stock product per warehouse on snapshot days: will it run
out within the horizon? Each model's decision threshold is the one with the best F1 on
the validation period; models are compared on the test period by PR-AUC (good at rare
events) and the best is selected (a network only if it beats the baseline). The report
also lists today's top reorder recommendations of the selected model, with reasons.

Run from ml/:  python -m training.train_reorder [--database PATH] [--models dense lstm]
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from baselines.reorder import reorder_point_score
from data_generation.database import DEFAULT_DATABASE, upgrade_database
from evaluation import metrics
from feature_engineering.reorder_features import (
    NUMERIC,
    Snapshots,
    StockHistory,
    build_stock_history,
    make_snapshots,
    snapshot_days,
)
from models.reorder.recommend import Recommendation, contributions, recommend
from registry.register_model import Selection
from training import keras_setup
from training.config import ExperimentConfig, load_config
from training.data import dataset_version, history_range, open_dataset
from training.experiment import ModelResult, Reporter, register_results, timer
from training.splits import chronological_split

USE_CASE = "reorder"
SELECTION_METRIC = "pr_auc"  # higher is better
REPORT = Path(__file__).resolve().parents[1] / "evaluation" / "reports" / f"{USE_CASE}.md"
FEATURES = [*NUMERIC, "category", "warehouse", "cover_bucket_x_peak", "month", "sequence"]
WARMUP_DAYS = 56


@dataclass
class ReorderRun:
    version: str
    dataset_version: str
    split_description: str
    sizes: dict[str, int]
    positives: dict[str, float]
    results: list[ModelResult]
    selection: Selection
    recommendations: list[Recommendation]


def model_inputs(model, inputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Only the inputs this model has (Keras matches extra inputs by position)."""
    return {tensor.name: inputs[tensor.name] for tensor in model.inputs}


def scored(label: np.ndarray, score: np.ndarray, threshold: float) -> dict[str, float]:
    result = metrics.classification_metrics(label, score, threshold)
    result["threshold"] = threshold
    result["flagged_share"] = float(np.mean(score >= threshold))
    return result


def _evaluate(name, is_baseline, sets, predict, seconds, **extra) -> ModelResult:
    valid_score = predict(sets["validation"].inputs())
    test_score = predict(sets["test"].inputs())
    threshold = metrics.best_f1_threshold(sets["validation"].label, valid_score)
    return ModelResult(
        name,
        is_baseline,
        scored(sets["validation"].label, valid_score, threshold),
        scored(sets["test"].label, test_score, threshold),
        seconds,
        **extra,
    )


def _snapshot_sets(
    history: StockHistory, config: ExperimentConfig, report: Reporter
) -> tuple[dict[str, Snapshots], str]:
    settings = config.features
    horizon = int(settings.get("horizon", 14))
    sequence_days = int(settings.get("sequence_days", 28))
    split = chronological_split(
        history.first,
        history.day(history.days - 1),
        validation_days=config.validation_days,
        test_days=config.test_days,
    )
    train_end = (split.train_end - history.first).days
    valid_end = (split.valid_end - history.first).days
    stride, eval_stride = int(settings.get("train_stride", 7)), int(settings.get("eval_stride", 7))
    days = {
        "train": snapshot_days(0, train_end, horizon=horizon, stride=stride, warmup=WARMUP_DAYS),
        "validation": snapshot_days(
            train_end + 1, valid_end, horizon=horizon, stride=eval_stride, warmup=WARMUP_DAYS
        ),
        "test": snapshot_days(
            valid_end + 1, history.days - 1, horizon=horizon, stride=eval_stride, warmup=WARMUP_DAYS
        ),
    }
    sets = {
        name: make_snapshots(history, d, horizon=horizon, sequence_days=sequence_days)
        for name, d in days.items()
    }
    limit = int(settings.get("max_train_rows", 0))
    if limit and len(sets["train"]) > limit:
        rng = np.random.default_rng(config.seed)
        sets["train"] = sets["train"].subset(np.sort(rng.choice(len(sets["train"]), limit, False)))
    report(f"  {split.describe()}")
    report(
        "  snapshots: "
        + ", ".join(f"{n} {len(s):,} ({s.label.mean():.1%} run out)" for n, s in sets.items())
    )
    return sets, split.describe()


def run(
    database: Path = DEFAULT_DATABASE,
    *,
    models: Sequence[str] | None = None,
    config: ExperimentConfig | None = None,
    report: Reporter = print,
    write_report: Path | None = REPORT,
    top: int = 15,
) -> ReorderRun:
    from models.reorder import ARCHITECTURES

    config = config or load_config(USE_CASE)
    names = list(config.models) if models is None else list(models)
    unknown = [n for n in names if n not in config.models]
    if unknown:
        raise ValueError(f"unknown model(s) {unknown}; configured: {list(config.models)}")
    engine = open_dataset(database)
    upgrade_database(database)
    version, data_version = keras_setup.new_version(), dataset_version(engine)
    first, last = history_range(engine)
    report(f"Reorder recommendation on {data_version}")
    history = build_stock_history(engine, first, last)
    sets, split_text = _snapshot_sets(history, config, report)
    lead = history.lead_days

    def baseline(inputs: dict[str, np.ndarray]) -> np.ndarray:
        numeric = inputs["numeric"]
        return reorder_point_score(
            np.expm1(numeric[:, NUMERIC.index("log_demand_28")]),
            numeric[:, NUMERIC.index("lead_days")],
            np.expm1(numeric[:, NUMERIC.index("log_position")]),
        )

    with timer() as elapsed:
        results = [_evaluate("reorder_point", True, sets, baseline, 0.0)]
        results[0].seconds = elapsed()
    report(f"  {'reorder_point':<14} test PR-AUC {results[0].test['pr_auc']:.3f} (baseline)")

    train, valid = sets["train"], sets["validation"]
    shapes = {name: value.shape[1:] for name, value in train.inputs().items()}
    trained = {}
    for name in names:
        with timer() as elapsed:
            keras_setup.set_seeds(config.seed)
            model = ARCHITECTURES[name](
                shapes, config.model(name), config.learning_rate, train.inputs()
            )
            artifact = keras_setup.artifact_path(USE_CASE, name, version)
            checkpoint = artifact.with_suffix(".checkpoint.keras")
            fit = model.fit(
                model_inputs(model, train.inputs()),
                train.label,
                validation_data=(model_inputs(model, valid.inputs()), valid.label),
                epochs=config.max_epochs,
                batch_size=config.batch_size,
                verbose=0,
                callbacks=keras_setup.training_callbacks(checkpoint, patience=config.patience),
            )
            keras_setup.save_model(model, artifact)
            checkpoint.unlink(missing_ok=True)

            def predict(inputs: dict[str, np.ndarray], model=model) -> np.ndarray:
                return model.predict(
                    model_inputs(model, inputs), batch_size=8192, verbose=0
                ).ravel()

            result = _evaluate(
                name,
                False,
                sets,
                predict,
                0.0,
                params=config.model(name),
                artifact=artifact,
                epochs=len(fit.history["loss"]),
            )
            result.seconds = elapsed()
        trained[name] = predict
        results.append(result)
        report(
            f"  {name:<14} test PR-AUC {result.test['pr_auc']:.3f} "
            f"({result.epochs} epochs, {result.seconds:.0f}s)"
        )

    selection = register_results(
        engine,
        results,
        use_case=USE_CASE,
        version=version,
        dataset_version=data_version,
        features=FEATURES,
        common_params={**config.features, "seed": config.seed},
        metric=SELECTION_METRIC,
        higher_is_better=True,
    )
    report(f"Selected: {selection.reason}")

    # Today's recommendations from the selected model (or the baseline).
    today_index = history.days - 1
    today = make_snapshots(
        history,
        [today_index],
        horizon=int(config.features.get("horizon", 14)),
        sequence_days=int(config.features.get("sequence_days", 28)),
    )
    chosen = next(r for r in results if r.name == selection.model_name)
    predict = trained.get(selection.model_name, baseline)
    probabilities = predict(today.inputs())
    effects = contributions(predict, today, train.numeric.to_numpy("float32").mean(axis=0))
    recommendations = recommend(
        today,
        probabilities,
        threshold=chosen.test["threshold"],
        product_ids=history.product_ids,
        warehouse_ids=history.warehouse_ids,
        lead_days=lead,
        today=history.day(today_index),
        factor_effects=effects,
    )
    engine.dispose()
    outcome = ReorderRun(
        version,
        data_version,
        split_text,
        {n: len(s) for n, s in sets.items()},
        {n: float(s.label.mean()) for n, s in sets.items()},
        results,
        selection,
        recommendations[:top],
    )
    if write_report is not None:
        write_report.parent.mkdir(parents=True, exist_ok=True)
        write_report.write_text(markdown_report(outcome), encoding="utf-8")
        report(f"Report: {write_report}")
    return outcome


def markdown_report(outcome: ReorderRun) -> str:
    columns = ["pr_auc", "roc_auc", "precision", "recall", "f1", "flagged_share", "brier", "ece"]
    lines = [
        "# Reorder recommendation: stockout-risk model comparison",
        "",
        f"- Dataset: `{outcome.dataset_version}`, training run `{outcome.version}`",
        f"- Split: {outcome.split_description}",
        "- Snapshots (in-stock product x warehouse x day): "
        + ", ".join(
            f"{n} {c:,} ({outcome.positives[n]:.1%} run out within the horizon)"
            for n, c in outcome.sizes.items()
        ),
        "- Metrics on the **test** period. `pr_auc` is used for the selection; precision, "
        "recall and F1 at each model's threshold (best F1 on validation); `flagged_share` is "
        "the share of snapshots flagged for reordering; `brier` and `ece` measure "
        "calibration (lower is better).",
        "",
        "| Model | Type | " + " | ".join(columns) + " | Epochs | Time |",
        "|---|---|" + "---:|" * (len(columns) + 2),
    ]
    for r in sorted(outcome.results, key=lambda r: -r.test[SELECTION_METRIC]):
        name = f"**{r.name}** (selected)" if r.name == outcome.selection.model_name else r.name
        kind = "baseline" if r.is_baseline else "Keras"
        values = " | ".join(f"{r.test[c]:.3f}" for c in columns)
        lines.append(f"| {name} | {kind} | {values} | {r.epochs or '-'} | {r.seconds:.0f} s |")
    lines += ["", f"**Selection:** {outcome.selection.reason}.", ""]
    if outcome.recommendations:
        lines += [
            f"## Top recommendations on {outcome.recommendations[0].reorder_date}",
            "",
            "| Product | Warehouse | Risk | Priority | Reorder on | Quantity | Main reasons |",
            "|---:|---:|---:|---|---|---:|---|",
        ]
        for rec in outcome.recommendations:
            lines.append(
                f"| {rec.product_id} | {rec.warehouse_id} | {rec.probability:.0%} | "
                f"{rec.priority} | {rec.reorder_date} | {rec.quantity} | "
                f"{'; '.join(rec.reasons) or '-'} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and compare stockout-risk models.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--models", nargs="+", help="networks to train (default: all)")
    args = parser.parse_args(argv)
    run(args.database, models=args.models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
