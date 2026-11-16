"""Experiment settings from YAML (ml/configs/): common.yaml plus one file per use case.

The use-case file overrides the common settings (nested keys are merged) and lists the
models to compare with their hyperparameters::

    # configs/demand_forecasting.yaml
    split:
      test_days: 120
    models:
      lstm: {units: 32, window: 28}
      gru: {units: 32, window: 28}
    features:            # settings of the use case's feature tables
      window: 56
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


class ConfigError(ValueError):
    """A configuration file is missing or invalid."""


@dataclass(frozen=True)
class ExperimentConfig:
    use_case: str
    seed: int
    validation_days: int
    test_days: int
    max_epochs: int
    batch_size: int
    learning_rate: float
    patience: int
    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)  # use-case settings (window, ...)

    def model(self, name: str) -> dict[str, Any]:
        if name not in self.models:
            raise ConfigError(f"no model {name!r} in the {self.use_case} configuration")
        return dict(self.models[name])


def merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """`override` on top of `base`; nested dictionaries are merged key by key."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def _read(path: Path) -> dict[str, Any]:
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file {path} not found") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return content


def _positive_int(values: dict[str, Any], key: str, source: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{source}: {key} must be a positive whole number, got {value!r}")
    return value


def load_config(use_case: str, directory: Path = CONFIG_DIR) -> ExperimentConfig:
    """common.yaml merged with `<use_case>.yaml` (which may be missing: defaults only)."""
    settings = _read(directory / "common.yaml")
    own = directory / f"{use_case}.yaml"
    if own.exists():
        settings = merge(settings, _read(own))
    split = settings.get("split") or {}
    training = settings.get("training") or {}
    models = settings.get("models") or {}
    features = settings.get("features") or {}
    if not isinstance(features, dict):
        raise ConfigError(f"{use_case}: features must be a mapping")
    if not isinstance(models, dict) or not all(
        isinstance(params or {}, dict) for params in models.values()
    ):
        raise ConfigError(f"{use_case}: models must map names to hyperparameter mappings")
    learning_rate = training.get("learning_rate")
    if isinstance(learning_rate, bool) or not isinstance(learning_rate, int | float):
        raise ConfigError(f"{use_case}: learning_rate must be a number")
    if not 0 < learning_rate < 1:
        raise ConfigError(f"{use_case}: learning_rate must be between 0 and 1")
    seed = settings.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ConfigError(f"{use_case}: seed must be a whole number >= 0")
    return ExperimentConfig(
        use_case=use_case,
        seed=seed,
        validation_days=_positive_int(split, "validation_days", use_case),
        test_days=_positive_int(split, "test_days", use_case),
        max_epochs=_positive_int(training, "max_epochs", use_case),
        batch_size=_positive_int(training, "batch_size", use_case),
        learning_rate=float(learning_rate),
        patience=_positive_int(training, "patience", use_case),
        models={name: dict(params or {}) for name, params in models.items()},
        features=dict(features),
    )
