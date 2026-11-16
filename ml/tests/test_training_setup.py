"""Chronological splits, YAML configs and feature schemas."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from feature_engineering.schema import FeatureSchema, SchemaError
from training.config import CONFIG_DIR, ConfigError, load_config, merge
from training.splits import TEST, TRAIN, VALIDATION, ChronologicalSplit, chronological_split

FIRST, LAST = date(2024, 11, 11), date(2026, 11, 10)


# ----------------------------------------------------------------------- splits
def test_split_keeps_the_most_recent_days_for_testing() -> None:
    split = chronological_split(FIRST, LAST, validation_days=60, test_days=90)
    assert split.valid_end == LAST - timedelta(days=90)
    assert split.train_end == LAST - timedelta(days=150)
    assert (split.train_days, split.validation_days, split.test_days) == (580, 60, 90)
    assert split.train_days + split.validation_days + split.test_days == 730
    assert split.period(split.train_end) == TRAIN
    assert split.period(split.train_end + timedelta(days=1)) == VALIDATION
    assert split.period(split.valid_end) == VALIDATION
    assert split.period(split.valid_end + timedelta(days=1)) == TEST
    assert "validation to 2026-08-12 (60)" in split.describe()


def test_no_day_is_in_two_periods_and_order_is_kept() -> None:
    split = chronological_split(FIRST, LAST, validation_days=60, test_days=90)
    days = pd.date_range(FIRST, LAST, freq="D")
    frame = pd.DataFrame({"day": days[::-1], "value": range(len(days))})  # newest first
    parts = split.split(frame, "day")
    assert sum(len(p) for p in parts.values()) == len(frame)
    assert parts[TRAIN]["day"].max() < parts[VALIDATION]["day"].min()
    assert parts[VALIDATION]["day"].max() < parts[TEST]["day"].min()
    assert list(parts[TEST]["value"]) == sorted(parts[TEST]["value"])  # original order
    assert len(parts[TEST]) == 90 and len(parts[VALIDATION]) == 60


def test_timestamps_with_times_and_time_zones() -> None:
    split = chronological_split(FIRST, LAST, validation_days=60, test_days=90)
    stamps = pd.Series(
        pd.to_datetime([f"{split.train_end} 23:59:59", f"{split.valid_end} 00:00:01"], utc=True)
    )
    assert list(split.assign(stamps)) == [TRAIN, VALIDATION]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"validation_days": 0, "test_days": 90}, "at least one day"),
        ({"validation_days": 400, "test_days": 320}, "training days"),
    ],
)
def test_split_errors(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        chronological_split(FIRST, LAST, **kwargs)


def test_dates_outside_the_history_are_refused() -> None:
    split = chronological_split(FIRST, LAST, validation_days=60, test_days=90)
    with pytest.raises(ValueError, match="outside"):
        split.assign([LAST + timedelta(days=1)])
    with pytest.raises(ValueError, match="outside"):
        split.period(FIRST - timedelta(days=1))
    with pytest.raises(ValueError, match="follow each other"):
        ChronologicalSplit(FIRST, LAST, LAST, LAST)


# ---------------------------------------------------------------------- configs
def test_common_config_defaults() -> None:
    config = load_config("demand_forecasting_not_configured_yet")
    assert config.seed == 20261111
    assert (config.validation_days, config.test_days) == (60, 90)
    assert (config.max_epochs, config.batch_size, config.patience) == (40, 256, 5)
    assert config.learning_rate == pytest.approx(0.001) and config.models == {}


def test_use_case_file_overrides_and_lists_models(tmp_path: Path) -> None:
    (tmp_path / "common.yaml").write_text((CONFIG_DIR / "common.yaml").read_text())
    (tmp_path / "demo.yaml").write_text(
        "split:\n  test_days: 120\ntraining:\n  batch_size: 64\n"
        "models:\n  lstm: {units: 32, window: 28}\n  baseline:\n"
    )
    config = load_config("demo", tmp_path)
    assert (config.validation_days, config.test_days, config.batch_size) == (60, 120, 64)
    assert config.model("lstm") == {"units": 32, "window": 28}
    assert config.model("baseline") == {}
    with pytest.raises(ConfigError, match="no model 'gru'"):
        config.model("gru")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("split:\n  test_days: 0\n", "test_days must be a positive"),
        ("split:\n  test_days: true\n", "test_days must be a positive"),
        ("training:\n  learning_rate: 2\n", "between 0 and 1"),
        ("training:\n  learning_rate: fast\n", "must be a number"),
        ("seed: -1\n", "seed"),
        ("models:\n  lstm: 32\n", "hyperparameter mappings"),
        ("- a list\n", "mapping at the top level"),
        ("split: [\n", "not valid YAML"),
    ],
)
def test_invalid_configs(tmp_path: Path, content: str, message: str) -> None:
    (tmp_path / "common.yaml").write_text((CONFIG_DIR / "common.yaml").read_text())
    (tmp_path / "bad.yaml").write_text(content)
    with pytest.raises(ConfigError, match=message):
        load_config("bad", tmp_path)


def test_missing_common_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config("demo", tmp_path)


def test_merge_is_deep_and_does_not_change_its_inputs() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": 1}
    assert merge(base, {"a": {"y": 3}, "c": 4}) == {"a": {"x": 1, "y": 3}, "b": 1, "c": 4}
    assert base == {"a": {"x": 1, "y": 2}, "b": 1}


# ---------------------------------------------------------------------- schemas
SCHEMA = FeatureSchema(
    "demo",
    {
        "units": "number",
        "lag": "integer",
        "weekday": "category",
        "promo": "flag",
        "day": "timestamp",
    },
)


def frame(**changes: object) -> pd.DataFrame:
    data: dict[str, object] = {
        "day": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        "units": [1.5, 2.0],
        "lag": [3, 4],
        "weekday": ["Thu", "Fri"],
        "promo": [0, 1],
    }
    data.update(changes)
    return pd.DataFrame(data)


def test_valid_frame_comes_back_in_schema_order() -> None:
    assert list(SCHEMA.validate(frame()).columns) == ["units", "lag", "weekday", "promo", "day"]
    assert SCHEMA.validate(frame(promo=[True, False])) is not None
    assert SCHEMA.of_kind("number", "integer") == ["units", "lag"]


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"units": [1.0, None]}, "units has 1 missing value"),
        ({"units": [1.0, np.inf]}, "units has infinite values"),
        ({"lag": [1.5, 2.0]}, "lag should be integer"),
        ({"promo": [0, 2]}, "promo should be flag"),
        ({"units": ["a", "b"]}, "units should be number"),
        ({"day": ["2026-01-01", "x"]}, "day should be timestamp"),
        ({"extra": [1, 2]}, "unexpected columns ['extra']"),
    ],
)
def test_schema_problems(changes: dict, problem: str) -> None:
    with pytest.raises(SchemaError) as error:
        SCHEMA.validate(frame(**changes))
    assert any(problem in p for p in error.value.problems)


def test_every_problem_is_reported() -> None:
    broken = frame(lag=[1.5, 2.0]).drop(columns=["units"])
    assert SCHEMA.problems(broken) == [
        "missing columns ['units']",
        "lag should be integer, is float64",
    ]


def test_schema_definition_errors() -> None:
    with pytest.raises(ValueError, match="unknown column kinds"):
        FeatureSchema("x", {"a": "text"})
    with pytest.raises(ValueError, match="at least one column"):
        FeatureSchema("x", {})
