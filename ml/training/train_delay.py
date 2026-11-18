"""Train and compare order-delay models (use case 5).

At dispatch, every model scores how likely the shipment is to arrive late. The logistic
regression baseline and the networks in configs/delay_prediction.yaml (Dense, Wide &
Deep, Deep & Cross, LSTM on order events) are trained on shipments dispatched in the
training period. Each model's threshold is the best-F1 one on the validation period;
models are compared on the test period by PR-AUC (late parcels are rare) and the best
is selected (a network only if it beats the baseline). Calibration (Brier, ECE) shows
whether "30 %" really means about 3 in 10. The report lists the riskiest recent
shipments with their risk level and main reasons.

Run from ml/:  python -m training.train_delay [--database PATH] [--models dense]
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from baselines.delay import LogisticBaseline
from data_generation.database import DEFAULT_DATABASE, upgrade_database
from evaluation import metrics
from feature_engineering.delay_features import NUMERIC, build_delay_set
from models.delay_prediction.explain import reasons, risk_level
from registry.register_model import Selection
from training import keras_setup
from training.config import ExperimentConfig, load_config
from training.data import dataset_version, history_range, open_dataset
from training.experiment import ModelResult, Reporter, register_results, timer
from training.splits import TEST, TRAIN, VALIDATION, chronological_split

USE_CASE = "delay_prediction"
SELECTION_METRIC = "pr_auc"  # higher is better
REPORT = Path(__file__).resolve().parents[1] / "evaluation" / "reports" / f"{USE_CASE}.md"
FEATURES = [*NUMERIC, "carrier", "warehouse", "priority", "customer_type", "status_events"]


@dataclass(frozen=True)
class RiskyShipment:
    order_id: int
    shipped: str
    probability: float
    level: str
    reasons: tuple[str, ...]
    late: bool


@dataclass
class DelayRun:
    version: str
    dataset_version: str
    split_description: str
    sizes: dict[str, int]
    late_share: dict[str, float]
    results: list[ModelResult]
    selection: Selection
    examples: list[RiskyShipment]


def model_inputs(model, inputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Only the inputs this model has (Keras matches extra inputs by position)."""
    return {tensor.name: inputs[tensor.name] for tensor in model.inputs}


def scored(label: np.ndarray, score: np.ndarray, threshold: float) -> dict[str, float]:
    result = metrics.classification_metrics(label, score, threshold)
    result["threshold"] = threshold
    result["flagged_share"] = float(np.mean(score >= threshold))
    return result


def _evaluate(name, is_baseline, sets, predict, **extra) -> ModelResult:
    valid = predict(sets[VALIDATION].inputs())
    test = predict(sets[TEST].inputs())
    threshold = metrics.best_f1_threshold(sets[VALIDATION].label, valid)
    return ModelResult(
        name,
        is_baseline,
        scored(sets[VALIDATION].label, valid, threshold),
        scored(sets[TEST].label, test, threshold),
        0.0,
        **extra,
    )


def run(
    database: Path = DEFAULT_DATABASE,
    *,
    models: Sequence[str] | None = None,
    config: ExperimentConfig | None = None,
    report: Reporter = print,
    write_report: Path | None = REPORT,
    examples: int = 10,
) -> DelayRun:
    from models.delay_prediction import ARCHITECTURES

    config = config or load_config(USE_CASE)
    names = list(config.models) if models is None else list(models)
    unknown = [n for n in names if n not in config.models]
    if unknown:
        raise ValueError(f"unknown model(s) {unknown}; configured: {list(config.models)}")
    engine = open_dataset(database)
    upgrade_database(database)
    version, data_version = keras_setup.new_version(), dataset_version(engine)
    first, last = history_range(engine)
    report(f"Order-delay prediction on {data_version}")
    data = build_delay_set(engine)
    split = chronological_split(
        first, last, validation_days=config.validation_days, test_days=config.test_days
    )
    periods = split.assign(data.shipped_day.astype(object))
    sets = {
        name: data.subset(np.flatnonzero(periods == name)) for name in (TRAIN, VALIDATION, TEST)
    }
    limit = int(config.features.get("max_train_rows", 0))
    if limit and len(sets[TRAIN]) > limit:
        rng = np.random.default_rng(config.seed)
        sets[TRAIN] = sets[TRAIN].subset(np.sort(rng.choice(len(sets[TRAIN]), limit, False)))
    train, valid = sets[TRAIN], sets[VALIDATION]
    report(f"  {split.describe()}")
    report(
        "  shipments: "
        + ", ".join(f"{n} {len(s):,} ({s.label.mean():.1%} late)" for n, s in sets.items())
    )

    with timer() as elapsed:
        baseline = LogisticBaseline(config.seed).fit(
            train.inputs()["numeric"], train.categorical, train.label
        )
        results = [_evaluate("logistic_regression", True, sets, baseline.predict)]
        results[0].seconds = elapsed()
    report(f"  {'logistic_regression':<20} test PR-AUC {results[0].test['pr_auc']:.3f} (baseline)")

    predictors = {"logistic_regression": baseline.predict}
    shapes = {k: v.shape[1:] for k, v in train.inputs().items()}
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
                params=config.model(name),
                artifact=artifact,
                epochs=len(fit.history["loss"]),
            )
            result.seconds = elapsed()
        predictors[name] = predict
        results.append(result)
        report(
            f"  {name:<20} test PR-AUC {result.test['pr_auc']:.3f} "
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
    engine.dispose()

    # The riskiest shipments of the last test week, explained by the selected model.
    test = sets[TEST]
    chosen = next(r for r in results if r.name == selection.model_name)
    recent = np.flatnonzero(test.shipped_day >= test.shipped_day.max() - np.timedelta64(6, "D"))
    week = test.subset(recent)
    predict = predictors[selection.model_name]
    probability = predict(week.inputs())
    top = np.argsort(-probability, kind="stable")[:examples]
    picked = week.subset(top)
    why = reasons(predict, picked.inputs(), train.inputs()["numeric"].mean(axis=0))
    risky = [
        RiskyShipment(
            int(picked.order_ids[i]),
            str(picked.shipped_day[i]),
            float(probability[top[i]]),
            risk_level(float(probability[top[i]]), chosen.test["threshold"]),
            why[i],
            bool(picked.label[i]),
        )
        for i in range(len(top))
    ]
    outcome = DelayRun(
        version,
        data_version,
        split.describe(),
        {n: len(s) for n, s in sets.items()},
        {n: float(s.label.mean()) for n, s in sets.items()},
        results,
        selection,
        risky,
    )
    if write_report is not None:
        write_report.parent.mkdir(parents=True, exist_ok=True)
        write_report.write_text(markdown_report(outcome), encoding="utf-8")
        report(f"Report: {write_report}")
    return outcome


def markdown_report(outcome: DelayRun) -> str:
    columns = ["pr_auc", "roc_auc", "precision", "recall", "f1", "flagged_share", "brier", "ece"]
    lines = [
        "# Order-delay prediction: model comparison",
        "",
        f"- Dataset: `{outcome.dataset_version}`, training run `{outcome.version}`",
        f"- Split by dispatch day: {outcome.split_description}",
        "- Delivered shipments: "
        + ", ".join(
            f"{n} {c:,} ({outcome.late_share[n]:.1%} late)" for n, c in outcome.sizes.items()
        ),
        "- Metrics on the **test** period. `pr_auc` is used for the selection; precision, "
        "recall and F1 for late parcels at each model's threshold (best F1 on validation); "
        "`flagged_share`: share of shipments flagged as at risk; `brier` and `ece`: "
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
    if outcome.examples:
        lines += [
            "## Riskiest shipments of the last test week (selected model)",
            "",
            "| Order | Dispatched | Delay risk | Level | Main reasons | Actually late |",
            "|---:|---|---:|---|---|---|",
        ]
        for e in outcome.examples:
            lines.append(
                f"| {e.order_id} | {e.shipped} | {e.probability:.0%} | {e.level} | "
                f"{'; '.join(e.reasons) or '-'} | {'yes' if e.late else 'no'} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and compare order-delay models.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--models", nargs="+", help="networks to train (default: all)")
    args = parser.parse_args(argv)
    run(args.database, models=args.models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
