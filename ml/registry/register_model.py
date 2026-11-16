"""Model registry: record every trained model and select the best one per use case
(project document 12.4 and 16.8; tables model_versions and model_metrics).

Selection follows "baselines first": all candidates of one training run are ranked on
the *test* period by one metric; a neural model is selected only if it is strictly
better than the best baseline, otherwise the baseline is selected. The previously
selected model of the use case is retired, so the application (Phase 9) always finds
exactly one selected model.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models.ml import MetricSplit, ModelMetric, ModelStatus, ModelVersion, UseCase


class RegistryError(ValueError):
    """Invalid registration or selection request."""


@dataclass(frozen=True)
class Selection:
    model_version_id: int
    model_name: str
    value: float
    reason: str


def register_model(
    engine: Engine,
    *,
    use_case: str,
    model_name: str,
    version: str,
    dataset_version: str,
    features: Sequence[str],
    hyperparameters: Mapping[str, Any],
    metrics: Mapping[str, Mapping[str, float]],
    artifact_path: str | None = None,
    is_baseline: bool = False,
    train_seconds: float | None = None,
    notes: str | None = None,
    trained_at: datetime | None = None,
) -> int:
    """Store one trained model with its metrics ({"validation": {...}, "test": {...}})."""
    if use_case not in set(UseCase):
        raise RegistryError(f"unknown use case {use_case!r}")
    unknown = set(metrics) - set(MetricSplit)
    if unknown:
        raise RegistryError(f"unknown metric split(s) {sorted(unknown)}")
    if not metrics.get(MetricSplit.TEST):
        raise RegistryError("test metrics are required: models are compared on the test period")
    if not is_baseline and artifact_path is None:
        raise RegistryError("a trained model needs its saved .keras file (artifact_path)")
    for split, values in metrics.items():
        for name, value in values.items():
            if value != value or value in (float("inf"), float("-inf")):  # NaN or infinite
                raise RegistryError(f"{split} metric {name} is not a finite number: {value}")
    row = ModelVersion(
        use_case=use_case,
        model_name=model_name,
        version=version,
        is_baseline=is_baseline,
        dataset_version=dataset_version,
        features=list(features),
        hyperparameters=dict(hyperparameters),
        artifact_path=artifact_path,
        trained_at=trained_at or datetime.now(UTC),
        train_seconds=train_seconds,
        notes=notes,
        metrics=[
            ModelMetric(split=split, name=name, value=float(value))
            for split, values in metrics.items()
            for name, value in values.items()
        ],
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        return row.id


def select_best(
    engine: Engine,
    use_case: str,
    candidate_ids: Sequence[int],
    *,
    metric: str,
    higher_is_better: bool,
) -> Selection:
    """Mark the best candidate (test period) as selected; see the module docstring."""
    if not candidate_ids:
        raise RegistryError("no candidates to choose from")
    with Session(engine) as session:
        candidates = session.scalars(
            select(ModelVersion).where(ModelVersion.id.in_(candidate_ids))
        ).all()
        if len(candidates) != len(set(candidate_ids)):
            raise RegistryError("some candidate ids do not exist")
        if any(c.use_case != use_case for c in candidates):
            raise RegistryError(f"all candidates must belong to {use_case}")
        if not any(c.is_baseline for c in candidates):
            raise RegistryError("a baseline is needed: models are only selected if they beat it")
        scored = []
        for candidate in candidates:
            value = candidate.metric(metric, MetricSplit.TEST)
            if value is None:
                raise RegistryError(f"{candidate.model_name} has no test {metric}")
            scored.append((value, candidate))

        def better(a: float, b: float) -> bool:
            return a > b if higher_is_better else a < b

        baseline_value, baseline = min(
            ((v, c) for v, c in scored if c.is_baseline),
            key=lambda item: -item[0] if higher_is_better else item[0],
        )
        best_value, best = baseline_value, baseline
        for value, candidate in scored:
            if not candidate.is_baseline and better(value, best_value):
                best_value, best = value, candidate
        if best is baseline:
            reason = (
                f"no model beat the baseline {baseline.model_name} "
                f"({metric} {baseline_value:.4g} on the test period)"
            )
        else:
            reason = (
                f"{best.model_name} beat the baseline {baseline.model_name}: "
                f"{metric} {best_value:.4g} vs {baseline_value:.4g} on the test period"
            )

        for previous in session.scalars(
            select(ModelVersion).where(
                ModelVersion.use_case == use_case, ModelVersion.status == ModelStatus.SELECTED
            )
        ):
            previous.status = ModelStatus.RETIRED
        session.flush()  # the database allows one selected model per use case
        best.status = ModelStatus.SELECTED
        session.commit()
        return Selection(best.id, best.model_name, best_value, reason)


def selected_model(engine: Engine, use_case: str) -> ModelVersion | None:
    """The model the application should use for a use case (None before any training)."""
    with Session(engine) as session:
        return session.scalars(
            select(ModelVersion).where(
                ModelVersion.use_case == use_case, ModelVersion.status == ModelStatus.SELECTED
            )
        ).one_or_none()
