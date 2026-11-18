"""The six ML use cases (project document 12.2): which training module trains each one
and how its models are compared. Used by scripts/train_models.py and
evaluation/compare_models.py."""

import dataclasses
import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from training.config import ExperimentConfig, load_config


@dataclass(frozen=True)
class UseCaseInfo:
    name: str  # registry name (app.models.ml.UseCase)
    title: str
    module: str  # training module with run(database, config=..., report=...)
    metric: str  # selection metric on the test period
    higher_is_better: bool
    metric_label: str  # in plain words, for the overview

    def runner(self) -> Callable[..., Any]:
        return importlib.import_module(self.module).run


USE_CASES = (
    UseCaseInfo(
        "demand_forecasting",
        "Demand forecasting",
        "training.train_demand",
        "wape_totals",
        False,
        "error of the 7/14/30-day demand totals (WAPE)",
    ),
    UseCaseInfo(
        "reorder",
        "Reorder recommendation",
        "training.train_reorder",
        "pr_auc",
        True,
        "stockout warnings (PR-AUC)",
    ),
    UseCaseInfo(
        "movement_classification",
        "Movement classification",
        "training.train_movement",
        "selection_score",
        True,
        "clear, stable and useful groups (silhouette if usable)",
    ),
    UseCaseInfo(
        "slotting",
        "Slotting",
        "training.train_slotting",
        "selection_score",
        True,
        "picking time saved vs. the current layout (0 rule violations)",
    ),
    UseCaseInfo(
        "delay_prediction",
        "Order-delay prediction",
        "training.train_delay",
        "pr_auc",
        True,
        "late-delivery warnings (PR-AUC)",
    ),
    UseCaseInfo(
        "recommendation",
        "Product recommendation",
        "training.train_recommendation",
        "ndcg_at_10",
        True,
        "held-out product ranked in the top 10 (NDCG@10)",
    ),
)
BY_NAME = {info.name: info for info in USE_CASES}


def quick_config(use_case: str, epochs: int = 1) -> ExperimentConfig:
    """A fast configuration for smoke tests: few epochs and small samples. Results are not
    meaningful; it only proves the whole pipeline runs."""
    config = load_config(use_case)
    models = {}
    for name, params in config.models.items():
        params = dict(params)
        for key in ("epochs", "pretrain_epochs"):
            if key in params:
                params[key] = max(epochs, 2)
        if "rounds" in params:
            params["rounds"] = 2
        models[name] = params
    features = dict(config.features)
    for key, small in (
        ("max_train_windows", 5000),
        ("max_train_rows", 5000),
        ("max_train_examples", 5000),
        ("eval_queries", 200),
        ("stability_runs", 2),
    ):
        if key in features:
            features[key] = min(features[key], small)
    return dataclasses.replace(
        config, max_epochs=epochs, patience=1, models=models, features=features
    )
