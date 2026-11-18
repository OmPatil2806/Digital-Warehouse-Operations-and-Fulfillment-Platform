"""Shared helpers of the predictors."""

import importlib
from dataclasses import dataclass
from datetime import date

import keras

from app.models.ml import MetricSplit, ModelVersion
from training import keras_setup
from training.config import ExperimentConfig, load_config
from training.splits import ChronologicalSplit, chronological_split


@dataclass
class Context:
    """What every predictor gets: the model to use and the days of data."""

    model: ModelVersion
    first: date
    last: date  # the last day of known data: predictions are "as of" this day

    @property
    def name(self) -> str:
        return self.model.model_name

    @property
    def is_baseline(self) -> bool:
        return self.model.is_baseline

    @property
    def params(self) -> dict:
        return dict(self.model.hyperparameters or {})

    @property
    def config(self) -> ExperimentConfig:
        return load_config(self.model.use_case)

    def split(self) -> ChronologicalSplit:
        """The training split of this history, as in training (for scales and baselines)."""
        config = self.config
        return chronological_split(
            self.first,
            self.last,
            validation_days=config.validation_days,
            test_days=config.test_days,
        )

    def threshold(self, default: float = 0.5) -> float:
        value = self.model.metric("threshold", MetricSplit.TEST)
        return default if value is None else float(value)

    def keras_model(self) -> keras.Model:
        if self.model.artifact_path is None:
            raise ValueError(f"{self.name} has no saved model")
        # The use case's model code registers its custom layers and losses; it must be
        # imported before Keras can rebuild a saved model.
        importlib.import_module(f"models.{self.model.use_case}")
        return keras_setup.load_model(keras_setup.ML_DIR / self.model.artifact_path)
