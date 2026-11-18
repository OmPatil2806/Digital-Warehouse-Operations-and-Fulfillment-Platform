"""Overview of the latest training run of every use case, read from the model registry.

For each use case: the selected model, the best baseline and the best network on the
test period, how much better the selected model is than the baseline, and every model
that took part. Written as markdown (evaluation/reports/overview.md by default); the
detailed comparison of each use case is in its own report next to it.

Run from ml/:  python -m evaluation.compare_models [--database PATH] [--output PATH]
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models.ml import MetricSplit, ModelStatus, ModelVersion
from data_generation.database import DEFAULT_DATABASE
from training.data import open_dataset
from training.use_cases import USE_CASES, UseCaseInfo

REPORTS = Path(__file__).resolve().parent / "reports"
OVERVIEW = REPORTS / "overview.md"


@dataclass
class UseCaseRun:
    info: UseCaseInfo
    version: str
    dataset_version: str
    models: list[ModelVersion]  # every model of the run, best first
    selected: ModelVersion

    def value(self, model: ModelVersion) -> float:
        value = model.metric(self.info.metric, MetricSplit.TEST)
        return float("nan") if value is None else value

    def shown(self, model: ModelVersion) -> str:
        """The test value as text; -1 on a selection score means the result was unusable
        (e.g. rule violations or unstable groups)."""
        value = self.value(model)
        if self.info.metric == "selection_score" and value == -1:
            return "not usable"
        return f"{value:.3f}"

    @property
    def best_baseline(self) -> ModelVersion:
        return next(m for m in self.models if m.is_baseline)

    @property
    def best_network(self) -> ModelVersion | None:
        return next((m for m in self.models if not m.is_baseline), None)

    @property
    def gain(self) -> float | None:
        """Relative improvement of the selected model over the best baseline (None when the
        baseline itself is selected or the comparison is not meaningful)."""
        if self.selected.is_baseline:
            return None
        base, best = self.value(self.best_baseline), self.value(self.selected)
        if base == 0 or base < 0:
            return None
        return (base - best) / base if not self.info.higher_is_better else (best - base) / base


def latest_runs(engine: Engine) -> list[UseCaseRun]:
    """The run that produced each use case's selected model (use cases never trained are
    left out)."""
    runs = []
    with Session(engine) as session:
        for info in USE_CASES:
            selected = session.scalars(
                select(ModelVersion).where(
                    ModelVersion.use_case == info.name,
                    ModelVersion.status == ModelStatus.SELECTED,
                )
            ).one_or_none()
            if selected is None:
                continue
            models = list(
                session.scalars(
                    select(ModelVersion).where(
                        ModelVersion.use_case == info.name,
                        ModelVersion.version == selected.version,
                    )
                )
            )
            run = UseCaseRun(info, selected.version, selected.dataset_version, models, selected)
            sign = -1 if info.higher_is_better else 1
            run.models.sort(key=lambda m, run=run: sign * run.value(m))
            runs.append(run)
    return runs


def overview_markdown(runs: Sequence[UseCaseRun]) -> str:
    lines = [
        "# Machine learning: overview of all use cases",
        "",
        "Every use case compares simple baselines with several TensorFlow/Keras models on "
        "the most recent period (test), which no model saw while training. A network is "
        "selected only if it beats the best baseline (project document 12.4).",
        "",
        "| Use case | Selected | Measured by | Selected | Best baseline | Best network | "
        "Gain over baseline |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for run in runs:
        network = run.best_network
        gain = run.gain
        lines.append(
            f"| {run.info.title} | **{run.selected.model_name}**"
            f"{' (baseline)' if run.selected.is_baseline else ''} | {run.info.metric_label} | "
            f"{run.value(run.selected):.3f} | {run.best_baseline.model_name} "
            f"{run.value(run.best_baseline):.3f} | "
            + (f"{network.model_name} {run.shown(network)}" if network else "-")
            + f" | {f'{gain:+.1%}' if gain is not None else 'baseline kept'} |"
        )
    if runs:
        datasets = sorted({run.dataset_version for run in runs})
        lines += ["", f"Dataset: {', '.join(f'`{d}`' for d in datasets)}."]
    for run in runs:
        lines += [
            "",
            f"## {run.info.title}",
            "",
            f"Training run `{run.version}`; {run.info.metric_label}: "
            f"`{run.info.metric}`, {'higher' if run.info.higher_is_better else 'lower'} is "
            f"better. Details: [{run.info.name}.md]({run.info.name}.md).",
            "",
            "| Model | Type | Test value | Status | Training time |",
            "|---|---|---:|---|---:|",
        ]
        for model in run.models:
            seconds = f"{model.train_seconds:.0f} s" if model.train_seconds is not None else "-"
            lines.append(
                f"| {model.model_name} | {'baseline' if model.is_baseline else 'Keras'} | "
                f"{run.shown(model)} | {model.status} | {seconds} |"
            )
    if not runs:
        lines += ["", "No trained models yet: run `python scripts/train_models.py`."]
    return "\n".join(lines) + "\n"


def write_overview(engine: Engine, output: Path = OVERVIEW) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(overview_markdown(latest_runs(engine)), encoding="utf-8")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Overview of the selected model per use case.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=OVERVIEW)
    args = parser.parse_args(argv)
    engine = open_dataset(args.database)
    path = write_overview(engine, args.output)
    engine.dispose()
    print(f"Overview: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
