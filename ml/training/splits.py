"""Chronological train / validation / test splits (project document 12.4).

Time-dependent data is never shuffled across time: the model learns from the past,
is tuned on the next period and judged on the most recent one, exactly as it would be
used in practice. Shuffling would let the future leak into training and make every
model look better than it is.

    |---------------- train ----------------|-- validation --|---- test ----|
    first day                       train_end        valid_end         last day
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

TRAIN, VALIDATION, TEST = "train", "validation", "test"
MIN_TRAIN_DAYS = 28


@dataclass(frozen=True)
class ChronologicalSplit:
    """Inclusive last days of the training and validation periods; test is the rest."""

    first: date
    train_end: date
    valid_end: date
    last: date

    def __post_init__(self) -> None:
        if not self.first <= self.train_end < self.valid_end < self.last:
            raise ValueError(f"periods must follow each other in time: {self}")

    @property
    def train_days(self) -> int:
        return (self.train_end - self.first).days + 1

    @property
    def validation_days(self) -> int:
        return (self.valid_end - self.train_end).days

    @property
    def test_days(self) -> int:
        return (self.last - self.valid_end).days

    def period(self, day: date) -> str:
        if day < self.first or day > self.last:
            raise ValueError(f"{day} is outside {self.first} to {self.last}")
        if day <= self.train_end:
            return TRAIN
        return VALIDATION if day <= self.valid_end else TEST

    def assign(self, days: Any) -> np.ndarray:
        """The period of each day ("train", "validation" or "test") for a date column."""
        values = pd.to_datetime(pd.Series(days)).dt.date
        if values.isna().any():
            raise ValueError("dates must not be missing")
        if values.min() < self.first or values.max() > self.last:
            raise ValueError(f"dates outside {self.first} to {self.last}")
        stamps = pd.to_datetime(values)
        return np.where(
            stamps <= pd.Timestamp(self.train_end),
            TRAIN,
            np.where(stamps <= pd.Timestamp(self.valid_end), VALIDATION, TEST),
        )

    def split(self, frame: pd.DataFrame, column: str) -> dict[str, pd.DataFrame]:
        """The rows of each period, in their original order."""
        periods = self.assign(frame[column])
        return {name: frame[periods == name] for name in (TRAIN, VALIDATION, TEST)}

    def describe(self) -> str:
        return (
            f"train {self.first} to {self.train_end} ({self.train_days} days), "
            f"validation to {self.valid_end} ({self.validation_days}), "
            f"test to {self.last} ({self.test_days})"
        )


def chronological_split(
    first: date, last: date, *, validation_days: int, test_days: int
) -> ChronologicalSplit:
    """The last `test_days` for testing, the `validation_days` before for validation."""
    if validation_days < 1 or test_days < 1:
        raise ValueError("validation and test periods need at least one day")
    valid_end = last - timedelta(days=test_days)
    train_end = valid_end - timedelta(days=validation_days)
    if (train_end - first).days + 1 < MIN_TRAIN_DAYS:
        raise ValueError(
            f"only {(train_end - first).days + 1} training days left; "
            f"at least {MIN_TRAIN_DAYS} are needed"
        )
    return ChronologicalSplit(first, train_end, valid_end, last)
