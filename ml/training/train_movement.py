"""Train and compare movement classification methods (use case 3): fast, medium and slow
movers.

Every method learns its groups from the products' movement over the training period.
It then classifies the products from their most recent 90 days and is judged on the
period that follows:

- **cluster quality** of the classes in feature space: silhouette (higher is better)
  and Davies-Bouldin (lower is better);
- **stability**: the same method trained with three seeds should find the same groups
  (adjusted Rand index; ABC is a fixed rule: 1.0);
- **business sense**: fast > medium > slow in next-period picks (`order_ok`), the rank
  correlation between class and next-period picks, the share of next-period picks that
  come from the "fast" class, and how many products keep their class (`persistence`).

Selection: `selection_score` = silhouette when the groups are usable, otherwise -1:
in business order, stable (>= MIN_STABILITY) and with a fast class that carries at least
MIN_FAST_PICK_SHARE of the next period's picks (what slotting needs). So a method only
wins with groups a manager can use; a learned method must beat ABC on it.

Run from ml/:  python -m training.train_movement [--database PATH]
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from baselines.movement import abc_classes
from data_generation.database import DEFAULT_DATABASE, upgrade_database
from evaluation import metrics
from feature_engineering.movement_features import (
    CLASSES,
    FEATURES,
    build_movement,
    movement_features,
    order_classes,
    picks_per_day,
)
from registry.register_model import Selection
from training import keras_setup
from training.config import ExperimentConfig, load_config
from training.data import dataset_version, history_range, open_dataset
from training.experiment import ModelResult, Reporter, register_results, timer
from training.splits import chronological_split

USE_CASE = "movement_classification"
SELECTION_METRIC = "selection_score"  # higher is better
MIN_STABILITY = 0.7
MIN_FAST_PICK_SHARE = 0.5  # the fast class must carry at least half of the coming picks
REPORT = Path(__file__).resolve().parents[1] / "evaluation" / "reports" / f"{USE_CASE}.md"


@dataclass
class MovementRun:
    version: str
    dataset_version: str
    split_description: str
    results: list[ModelResult]
    selection: Selection


def evaluate(
    classes: np.ndarray,
    features_std: np.ndarray,
    next_picks: np.ndarray,
    fitted_classes: np.ndarray,
    stability: float,
) -> dict[str, float]:
    """Metrics of one classification (0 slow, 1 medium, 2 fast) of one period."""
    result: dict[str, float] = {"stability": stability}
    if len(np.unique(classes)) >= 2:
        result.update(metrics.clustering_metrics(features_std, classes))
    else:
        result.update({"silhouette": -1.0, "davies_bouldin": 99.0})
    means = [next_picks[classes == c].mean() for c in range(3) if (classes == c).any()]
    result["order_ok"] = float(all(a < b for a, b in zip(means, means[1:], strict=False)))
    result["rank_correlation"] = metrics.rank_correlation(classes, next_picks)
    total = next_picks.sum()
    result["fast_pick_share"] = float(next_picks[classes == 2].sum() / total) if total else 0.0
    result["persistence"] = float(np.mean(classes == fitted_classes))
    for c, name in enumerate(CLASSES):
        result[f"share_{name}"] = float(np.mean(classes == c))
    usable = (
        result["order_ok"] == 1
        and stability >= MIN_STABILITY
        and result["fast_pick_share"] >= MIN_FAST_PICK_SHARE
    )
    result[SELECTION_METRIC] = result["silhouette"] if usable else -1.0
    return result


def run(
    database: Path = DEFAULT_DATABASE,
    *,
    models: Sequence[str] | None = None,
    config: ExperimentConfig | None = None,
    report: Reporter = print,
    write_report: Path | None = REPORT,
) -> MovementRun:
    from models.movement_classification import METHODS

    config = config or load_config(USE_CASE)
    names = list(config.models) if models is None else list(models)
    unknown = [n for n in names if n not in config.models]
    if unknown:
        raise ValueError(f"unknown model(s) {unknown}; configured: {list(config.models)}")
    engine = open_dataset(database)
    upgrade_database(database)
    version, data_version = keras_setup.new_version(), dataset_version(engine)
    first, last = history_range(engine)
    report(f"Movement classification on {data_version}")
    movement = build_movement(engine, first, last)
    split = chronological_split(
        first, last, validation_days=config.validation_days, test_days=config.test_days
    )
    train_end, valid_end = (split.train_end - first).days, (split.valid_end - first).days
    recent = int(config.features.get("recent_days", 90))
    seeds = [config.seed + i for i in range(int(config.features.get("stability_runs", 3)))]

    columns = list(config.features.get("columns", FEATURES))
    unknown_columns = sorted(set(columns) - set(FEATURES))
    if unknown_columns:
        raise ValueError(f"unknown movement features {unknown_columns}")

    def features(start: int, end: int) -> np.ndarray:
        return movement_features(movement, start, end)[columns].to_numpy("float32")

    fit_raw = features(0, train_end)
    mean, variance = fit_raw.mean(axis=0), fit_raw.var(axis=0) + 1e-6

    def standard(values: np.ndarray) -> np.ndarray:
        return ((values - mean) / np.sqrt(variance)).astype("float32")

    periods = {  # features of the recent days -> judged on the next period
        "validation": (
            features(train_end - recent + 1, train_end),
            picks_per_day(movement, train_end + 1, valid_end),
        ),
        "test": (
            features(valid_end - recent + 1, valid_end),
            picks_per_day(movement, valid_end + 1, movement.days - 1),
        ),
    }
    activity = movement_features(movement, 0, train_end)["log_lines_per_day"].to_numpy()
    report(f"  {split.describe()}; {len(fit_raw):,} products, classes from the last {recent} days")

    recent_picks = {  # ABC ranks by the picks of the same recent days
        "validation": picks_per_day(movement, train_end - recent + 1, train_end),
        "test": picks_per_day(movement, valid_end - recent + 1, valid_end),
    }
    results = []
    with timer() as elapsed:
        fitted = abc_classes(picks_per_day(movement, 0, train_end))
        scores = {
            name: evaluate(abc_classes(recent_picks[name]), standard(raw), picks, fitted, 1.0)
            for name, (raw, picks) in periods.items()
        }
        results.append(ModelResult("abc", True, scores["validation"], scores["test"], elapsed()))
    report(f"  {'abc':<20} test score {scores['test'][SELECTION_METRIC]:.3f} (baseline)")

    for name in names:
        params = config.model(name)
        with timer() as elapsed:
            runs = [
                METHODS[name](standard(fit_raw), params, seed, mean, variance) for seed in seeds
            ]
            stability = metrics.cluster_stability([r.labels(fit_raw) for r in runs])
            clusterer = runs[0]
            raw_labels = clusterer.labels(fit_raw)
            ordered = order_classes(raw_labels, activity)
            mapping = {int(c): int(ordered[raw_labels == c][0]) for c in np.unique(raw_labels)}

            def classify(raw: np.ndarray, clusterer=clusterer, mapping=mapping) -> np.ndarray:
                labels = clusterer.labels(raw)
                return np.array([mapping.get(int(c), 0) for c in labels])

            scores = {
                period: evaluate(classify(raw), standard(raw), picks, ordered, stability)
                for period, (raw, picks) in periods.items()
            }
            artifact = keras_setup.save_model(
                clusterer.model, keras_setup.artifact_path(USE_CASE, name, version)
            )
            result = ModelResult(
                name,
                False,
                scores["validation"],
                scores["test"],
                elapsed(),
                params={
                    **params,
                    "class_of_cluster": {str(k): CLASSES[v] for k, v in mapping.items()},
                },
                artifact=artifact,
                epochs=clusterer.epochs,
            )
        results.append(result)
        report(
            f"  {name:<20} test score {result.test[SELECTION_METRIC]:.3f} "
            f"(silhouette {result.test['silhouette']:.3f}, stability {stability:.2f}, "
            f"{result.seconds:.0f}s)"
        )

    selection = register_results(
        engine,
        results,
        use_case=USE_CASE,
        version=version,
        dataset_version=data_version,
        features=columns,
        common_params={**config.features, "seed": config.seed},
        metric=SELECTION_METRIC,
        higher_is_better=True,
    )
    report(f"Selected: {selection.reason}")
    engine.dispose()
    outcome = MovementRun(version, data_version, split.describe(), results, selection)
    if write_report is not None:
        write_report.parent.mkdir(parents=True, exist_ok=True)
        write_report.write_text(markdown_report(outcome), encoding="utf-8")
        report(f"Report: {write_report}")
    return outcome


def markdown_report(outcome: MovementRun) -> str:
    columns = [
        SELECTION_METRIC,
        "silhouette",
        "davies_bouldin",
        "stability",
        "order_ok",
        "rank_correlation",
        "fast_pick_share",
        "persistence",
        "share_fast",
        "share_medium",
        "share_slow",
    ]
    lines = [
        "# Movement classification: method comparison",
        "",
        f"- Dataset: `{outcome.dataset_version}`, training run `{outcome.version}`",
        f"- Split: {outcome.split_description}",
        "- Each method learns its groups on the training period, classifies products from "
        "their most recent 90 days and is judged on the **test** period that follows.",
        f"- `{SELECTION_METRIC}` = silhouette when the groups are usable, otherwise -1: in "
        "business order (`order_ok`: fast > medium > slow in next-period picks), stable "
        f"(`stability` >= {MIN_STABILITY} across seeds) and with a fast class carrying at "
        f"least {MIN_FAST_PICK_SHARE:.0%} of the next period's picks (`fast_pick_share`). "
        "`persistence`: share of products keeping their training-period class.",
        "",
        "| Method | Type | " + " | ".join(columns) + " | Time |",
        "|---|---|" + "---:|" * (len(columns) + 1),
    ]
    for r in sorted(outcome.results, key=lambda r: -r.test[SELECTION_METRIC]):
        name = f"**{r.name}** (selected)" if r.name == outcome.selection.model_name else r.name
        kind = "baseline" if r.is_baseline else "Keras + clustering"
        values = " | ".join(f"{r.test[c]:.3f}" for c in columns)
        lines.append(f"| {name} | {kind} | {values} | {r.seconds:.0f} s |")
    lines += ["", f"**Selection:** {outcome.selection.reason}."]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and compare movement classification.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--models", nargs="+", help="methods to train (default: all)")
    args = parser.parse_args(argv)
    run(args.database, models=args.models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
