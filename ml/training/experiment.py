"""Shared bookkeeping of a training run: results per model, registration and selection."""

import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from registry.register_model import Selection, register_model, select_best
from training import keras_setup

Reporter = Callable[[str], None]


@dataclass
class ModelResult:
    name: str
    is_baseline: bool
    validation: dict[str, float]
    test: dict[str, float]
    seconds: float
    params: dict[str, Any] = field(default_factory=dict)
    artifact: Path | None = None
    epochs: int = 0
    model_version_id: int | None = None


@contextmanager
def timer() -> Iterator[Callable[[], float]]:
    started = time.perf_counter()
    yield lambda: time.perf_counter() - started


def register_results(
    engine: Engine,
    results: Sequence[ModelResult],
    *,
    use_case: str,
    version: str,
    dataset_version: str,
    features: Sequence[str],
    common_params: dict[str, Any],
    metric: str,
    higher_is_better: bool,
) -> Selection:
    """Register every result (baselines too) and select the best by `metric` on test."""
    for result in results:
        result.model_version_id = register_model(
            engine,
            use_case=use_case,
            model_name=result.name,
            version=version,
            dataset_version=dataset_version,
            features=list(features),
            hyperparameters={**common_params, **result.params, "epochs": result.epochs},
            metrics={"validation": result.validation, "test": result.test},
            artifact_path=keras_setup.relative_to_ml(result.artifact) if result.artifact else None,
            is_baseline=result.is_baseline,
            train_seconds=result.seconds,
        )
    return select_best(
        engine,
        use_case,
        [r.model_version_id for r in results if r.model_version_id is not None],
        metric=metric,
        higher_is_better=higher_is_better,
    )
