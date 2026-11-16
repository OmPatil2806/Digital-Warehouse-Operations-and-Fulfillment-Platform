"""Train and compare demand forecasting models (use case 1).

Baselines (moving average, seasonal naive) and the networks in
configs/demand_forecasting.yaml (LSTM, GRU, CNN-LSTM, Transformer) forecast the next 30
days of every product. All are measured the same way on the validation and test periods;
every model is registered, and the best on the test period by WAPE is selected (a
network only if it beats the best baseline).

Run from ml/:  python -m training.train_demand [--database PATH] [--models lstm gru]
"""

import argparse
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from baselines.demand import BASELINES
from data_generation.database import DEFAULT_DATABASE, upgrade_database
from evaluation import metrics
from feature_engineering.demand_features import (
    FUTURE_FEATURES,
    HISTORY_FEATURES,
    DemandData,
    Windows,
    build_demand_data,
    make_windows,
    origins_between,
    product_scale,
)
from registry.register_model import Selection, register_model, select_best
from training import keras_setup
from training.config import ExperimentConfig, load_config
from training.data import dataset_version, history_range, open_dataset
from training.splits import chronological_split

USE_CASE = "demand_forecasting"
# Lower is better: the average WAPE of the 7-, 14- and 30-day demand totals per product,
# the numbers stock planning uses (daily WAPE is reported too).
SELECTION_METRIC = "wape_totals"
REPORT = Path(__file__).resolve().parents[1] / "evaluation" / "reports" / f"{USE_CASE}.md"
FEATURES = [f"history:{name}" for name in HISTORY_FEATURES] + [
    f"future:{name}" for name in FUTURE_FEATURES
]

Reporter = Callable[[str], None]


@dataclass
class ModelResult:
    name: str
    is_baseline: bool
    validation: dict[str, float]
    test: dict[str, float]
    seconds: float
    params: dict = field(default_factory=dict)
    artifact: Path | None = None
    epochs: int = 0
    model_version_id: int | None = None


@dataclass
class DemandRun:
    version: str
    dataset_version: str
    split_description: str
    windows: dict[str, int]
    results: list[ModelResult]
    selection: Selection | None


def forecast_metrics(predicted: np.ndarray, actual: np.ndarray) -> dict[str, float]:
    """`predicted` (n, horizon, 3) low/middle/high, `actual` (n, horizon) units."""
    middle = predicted[:, :, 1]
    result = {
        "mae": metrics.mae(actual, middle),
        "rmse": metrics.rmse(actual, middle),
        "wape": metrics.wape(actual, middle),
        "coverage_80": metrics.interval_coverage(actual, predicted[:, :, 0], predicted[:, :, 2]),
    }
    totals = []
    for days in (7, 14, 30):
        if actual.shape[1] >= days:
            result[f"wape_{days}d_total"] = metrics.wape(
                actual[:, :days].sum(axis=1), middle[:, :days].sum(axis=1)
            )
            totals.append(result[f"wape_{days}d_total"])
    result["wape_totals"] = float(np.mean(totals)) if totals else result["wape"]
    return result


def _windows(
    data: DemandData, config: ExperimentConfig, report: Reporter
) -> tuple[dict[str, Windows], str]:
    settings = config.features
    window, horizon = int(settings.get("window", 56)), int(settings.get("horizon", 30))
    split = chronological_split(
        data.first,
        data.day(data.days - 1),
        validation_days=config.validation_days,
        test_days=config.test_days,
    )
    train_end, valid_end = data.day_index(split.train_end), data.day_index(split.valid_end)
    scale = product_scale(data, until=train_end + 1)  # learned from training days only
    stride, eval_stride = int(settings.get("train_stride", 3)), int(settings.get("eval_stride", 7))
    periods = {
        "train": origins_between(0, train_end, window=window, horizon=horizon, stride=stride),
        "validation": origins_between(
            train_end + 1 - window, valid_end, window=window, horizon=horizon, stride=eval_stride
        ),
        "test": origins_between(
            valid_end + 1 - window,
            data.days - 1,
            window=window,
            horizon=horizon,
            stride=eval_stride,
        ),
    }
    built = {
        name: make_windows(data, origins, window=window, horizon=horizon, scale=scale)
        for name, origins in periods.items()
    }
    limit = int(settings.get("max_train_windows", 0))
    if limit and len(built["train"]) > limit:  # a random, reproducible sample
        keep = np.sort(np.random.default_rng(config.seed).choice(len(built["train"]), limit, False))
        built["train"] = built["train"].subset(keep)
    report(f"  {split.describe()}")
    report("  windows: " + ", ".join(f"{name} {len(w):,}" for name, w in built.items()))
    return built, split.describe()


def _train_network(
    name: str,
    windows: dict[str, Windows],
    config: ExperimentConfig,
    version: str,
) -> tuple[np.ndarray, np.ndarray, Path, int]:
    from models.demand_forecasting import ARCHITECTURES

    train, valid = windows["train"], windows["validation"]
    shapes = {
        "window": train.history.shape[1],
        "horizon": train.target.shape[1],
        "history_features": train.history.shape[2],
        "future_features": train.future.shape[2],
        "static": train.static.shape[1],
    }
    keras_setup.set_seeds(config.seed)
    model = ARCHITECTURES[name](shapes, config.model(name), config.learning_rate)
    artifact = keras_setup.artifact_path(USE_CASE, name, version)
    history = model.fit(
        train.inputs(),
        train.target / train.scale[:, None],
        validation_data=(valid.inputs(), valid.target / valid.scale[:, None]),
        epochs=config.max_epochs,
        batch_size=config.batch_size,
        shuffle=True,
        verbose=0,
        callbacks=keras_setup.training_callbacks(
            artifact.with_suffix(".checkpoint.keras"), patience=config.patience
        ),
    )
    keras_setup.save_model(model, artifact)
    artifact.with_suffix(".checkpoint.keras").unlink(missing_ok=True)

    def predict(w: Windows) -> np.ndarray:
        scaled = model.predict(w.inputs(), batch_size=4096, verbose=0)
        return np.maximum(scaled * w.scale[:, None, None], 0)

    return predict(valid), predict(windows["test"]), artifact, len(history.history["loss"])


def run(
    database: Path = DEFAULT_DATABASE,
    *,
    models: Sequence[str] | None = None,
    config: ExperimentConfig | None = None,
    report: Reporter = print,
    write_report: Path | None = REPORT,
) -> DemandRun:
    """Train, evaluate, register and select. `models` limits the networks trained."""
    config = config or load_config(USE_CASE)
    names = list(config.models) if models is None else list(models)
    unknown = [n for n in names if n not in config.models]
    if unknown:
        raise ValueError(f"unknown model(s) {unknown}; configured: {list(config.models)}")
    engine = open_dataset(database)
    upgrade_database(database)  # older datasets get the registry tables
    version = keras_setup.new_version()
    data_version = dataset_version(engine)
    first, last = history_range(engine)
    report(f"Demand forecasting on {data_version}")
    data = build_demand_data(engine, first, last)
    windows, split_text = _windows(data, config, report)
    horizon = windows["test"].target.shape[1]
    results: list[ModelResult] = []

    for name, baseline in BASELINES.items():
        started = time.perf_counter()
        scored = {
            period: forecast_metrics(
                baseline(windows[period].raw_history(), horizon), windows[period].target
            )
            for period in ("validation", "test")
        }
        results.append(
            ModelResult(
                name,
                True,
                scored["validation"],
                scored["test"],
                time.perf_counter() - started,
            )
        )
        report(
            f"  {name:<16} test WAPE of totals {scored['test'][SELECTION_METRIC]:.3f} (baseline)"
        )

    for name in names:
        started = time.perf_counter()
        valid_pred, test_pred, artifact, epochs = _train_network(name, windows, config, version)
        seconds = time.perf_counter() - started
        result = ModelResult(
            name,
            False,
            forecast_metrics(valid_pred, windows["validation"].target),
            forecast_metrics(test_pred, windows["test"].target),
            seconds,
            params=config.model(name),
            artifact=artifact,
            epochs=epochs,
        )
        results.append(result)
        report(
            f"  {name:<16} test WAPE of totals {result.test[SELECTION_METRIC]:.3f} "
            f"({epochs} epochs, {seconds:.0f}s)"
        )

    hyper_common = {**config.features, "seed": config.seed}
    for result in results:
        result.model_version_id = register_model(
            engine,
            use_case=USE_CASE,
            model_name=result.name,
            version=version,
            dataset_version=data_version,
            features=FEATURES,
            hyperparameters={**hyper_common, **result.params, "epochs": result.epochs},
            metrics={"validation": result.validation, "test": result.test},
            artifact_path=keras_setup.relative_to_ml(result.artifact) if result.artifact else None,
            is_baseline=result.is_baseline,
            train_seconds=result.seconds,
        )
    selection = select_best(
        engine,
        USE_CASE,
        [r.model_version_id for r in results if r.model_version_id is not None],
        metric=SELECTION_METRIC,
        higher_is_better=False,
    )
    report(f"Selected: {selection.reason}")
    engine.dispose()
    outcome = DemandRun(
        version,
        data_version,
        split_text,
        {name: len(w) for name, w in windows.items()},
        results,
        selection,
    )
    if write_report is not None:
        write_report.parent.mkdir(parents=True, exist_ok=True)
        write_report.write_text(markdown_report(outcome), encoding="utf-8")
        report(f"Report: {write_report}")
    return outcome


def markdown_report(outcome: DemandRun) -> str:
    columns = [
        "wape_totals",
        "wape_7d_total",
        "wape_14d_total",
        "wape_30d_total",
        "wape",
        "mae",
        "rmse",
        "coverage_80",
    ]
    lines = [
        "# Demand forecasting: model comparison",
        "",
        f"- Dataset: `{outcome.dataset_version}`, training run `{outcome.version}`",
        f"- Split: {outcome.split_description}",
        "- Forecast windows: "
        + ", ".join(f"{name} {count:,}" for name, count in outcome.windows.items()),
        "- Metrics on the **test** period, per product: `wape_totals` (used for the selection) "
        "is the average WAPE of the 7-, 14- and 30-day demand totals; `wape`, `mae`, `rmse` "
        "are per day. Lower is better, except `coverage_80`: the share of days inside the "
        "forecast range (ideal 0.80)",
        "",
        "| Model | Type | " + " | ".join(columns) + " | Epochs | Time |",
        "|---|---|" + "---:|" * (len(columns) + 2),
    ]
    best = outcome.selection.model_name if outcome.selection else None
    for r in sorted(outcome.results, key=lambda r: r.test[SELECTION_METRIC]):
        name = f"**{r.name}** (selected)" if r.name == best else r.name
        kind = "baseline" if r.is_baseline else "Keras"
        values = " | ".join(f"{r.test.get(c, float('nan')):.3f}" for c in columns)
        lines.append(f"| {name} | {kind} | {values} | {r.epochs or '-'} | {r.seconds:.0f} s |")
    if outcome.selection:
        lines += ["", f"**Selection:** {outcome.selection.reason}."]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and compare demand forecasting models.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--models", nargs="+", help="networks to train (default: all)")
    args = parser.parse_args(argv)
    run(args.database, models=args.models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
