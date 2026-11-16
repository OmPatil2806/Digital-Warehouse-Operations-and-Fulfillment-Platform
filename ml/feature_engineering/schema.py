"""Feature schemas: the exact columns a model expects, checked before training and
before every prediction (project document 16.8, "feature schema tests").

A model trained on one set of columns silently gives nonsense on another, so every
feature table is validated against its schema: all columns present (no extras), the
right kind of values, nothing missing or infinite.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from pandas.api import types

NUMBER, INTEGER, CATEGORY, FLAG, TIMESTAMP = "number", "integer", "category", "flag", "timestamp"
KINDS = (NUMBER, INTEGER, CATEGORY, FLAG, TIMESTAMP)


class SchemaError(ValueError):
    """A feature table does not match its schema; `problems` lists every difference."""

    def __init__(self, name: str, problems: list[str]) -> None:
        super().__init__(f"{name}: " + "; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class FeatureSchema:
    name: str
    columns: dict[str, str]  # column -> kind (number, integer, category, flag, timestamp)

    def __post_init__(self) -> None:
        unknown = {kind for kind in self.columns.values() if kind not in KINDS}
        if unknown:
            raise ValueError(f"unknown column kinds: {sorted(unknown)}")
        if not self.columns:
            raise ValueError("a schema needs at least one column")

    @property
    def names(self) -> list[str]:
        return list(self.columns)

    def of_kind(self, *kinds: str) -> list[str]:
        return [column for column, kind in self.columns.items() if kind in kinds]

    def problems(self, frame: pd.DataFrame) -> list[str]:
        found: list[str] = []
        missing = [c for c in self.columns if c not in frame.columns]
        extra = [c for c in frame.columns if c not in self.columns]
        if missing:
            found.append(f"missing columns {missing}")
        if extra:
            found.append(f"unexpected columns {extra}")
        for column, kind in self.columns.items():
            if column not in frame.columns:
                continue
            values = frame[column]
            if values.isna().any():
                found.append(f"{column} has {int(values.isna().sum())} missing value(s)")
                continue
            if not _matches(values, kind):
                found.append(f"{column} should be {kind}, is {values.dtype}")
            elif kind in (NUMBER, INTEGER) and not np.isfinite(values.to_numpy(float)).all():
                found.append(f"{column} has infinite values")
        return found

    def validate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """The frame with its columns in schema order; SchemaError if anything differs."""
        found = self.problems(frame)
        if found:
            raise SchemaError(self.name, found)
        return frame[self.names]


def _matches(values: pd.Series, kind: str) -> bool:
    if kind == NUMBER:
        return types.is_numeric_dtype(values) and not types.is_bool_dtype(values)
    if kind == INTEGER:
        return types.is_integer_dtype(values) and not types.is_bool_dtype(values)
    if kind == FLAG:
        return types.is_bool_dtype(values) or (
            types.is_integer_dtype(values) and values.isin((0, 1)).all()
        )
    if kind == TIMESTAMP:
        return types.is_datetime64_any_dtype(values)
    return (
        isinstance(values.dtype, pd.CategoricalDtype)
        or types.is_string_dtype(values)
        or types.is_object_dtype(values)
        or (types.is_integer_dtype(values) and not types.is_bool_dtype(values))
    )
