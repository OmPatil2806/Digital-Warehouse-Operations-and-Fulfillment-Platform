"""Movement classification features: how each product moves over a period.

Per product, from its daily order lines (each line is one pick) and units:

| Feature                | Meaning                                               |
|------------------------|-------------------------------------------------------|
| log_lines_per_day      | how often it is picked                                |
| log_units_per_day      | how much of it leaves                                 |
| sale_day_share         | share of days it sells at all                         |
| log_cv_daily           | how irregular daily demand is                         |
| log_cv_weekly          | how irregular weekly demand is                        |
| trend                  | last third of the period vs the first (log ratio)     |
| log_units_per_line     | typical order size                                    |
| log_mean_gap_days      | average days between sales                            |

Classes are learned on one period and judged on the *next*: a product classed "fast"
now should be picked most in the coming weeks (that is how slotting will use it).
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from feature_engineering.schema import FeatureSchema
from training.data import read_frame

FEATURES = (
    "log_lines_per_day",
    "log_units_per_day",
    "sale_day_share",
    "log_cv_daily",
    "log_cv_weekly",
    "trend",
    "log_units_per_line",
    "log_mean_gap_days",
)
SCHEMA = FeatureSchema("product_movement", dict.fromkeys(FEATURES, "number"))
CLASSES = ("slow", "medium", "fast")


@dataclass
class Movement:
    """Daily order lines and units per product (rows follow product_ids)."""

    product_ids: np.ndarray
    first: date
    lines: np.ndarray  # (products, days)
    units: np.ndarray  # (products, days)

    @property
    def days(self) -> int:
        return self.lines.shape[1]


def build_movement(engine: Engine, first: date, last: date) -> Movement:
    products = read_frame(engine, "SELECT id FROM products ORDER BY id")["id"].to_numpy()
    days = (last - first).days + 1
    daily = read_frame(
        engine,
        "SELECT oi.product_id, date(o.created_at) AS day, COUNT(*) AS lines, "
        "SUM(oi.quantity) AS units FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "GROUP BY 1, 2",
    )
    offsets = (pd.to_datetime(daily["day"]) - pd.Timestamp(first)).dt.days.to_numpy()
    rows = np.searchsorted(products, daily["product_id"].to_numpy())
    keep = (offsets >= 0) & (offsets < days)
    lines = np.zeros((len(products), days), "float32")
    units = np.zeros((len(products), days), "float32")
    lines[rows[keep], offsets[keep]] = daily["lines"].to_numpy()[keep]
    units[rows[keep], offsets[keep]] = daily["units"].to_numpy()[keep]
    return Movement(products, first, lines, units)


def movement_features(movement: Movement, start: int, end: int) -> pd.DataFrame:
    """Features over days start..end (day indices, inclusive), one row per product."""
    if not 0 <= start <= end < movement.days:
        raise ValueError(f"period {start}..{end} is outside the history")
    if end - start + 1 < 21:
        raise ValueError("a period needs at least 21 days (three weeks)")
    lines = movement.lines[:, start : end + 1].astype(float)
    units = movement.units[:, start : end + 1].astype(float)
    days = lines.shape[1]
    mean_units = units.mean(axis=1)
    weeks = units[:, : days // 7 * 7].reshape(len(units), -1, 7).sum(axis=2)
    third = max(days // 3, 1)
    sold = lines > 0
    sale_days = sold.sum(axis=1)
    gaps = np.where(sale_days > 1, (days - 1) / np.maximum(sale_days - 1, 1), days)

    def cv(values: np.ndarray) -> np.ndarray:
        mean = values.mean(axis=1)
        return np.where(mean > 0, values.std(axis=1) / np.maximum(mean, 1e-9), 0.0)

    frame = pd.DataFrame(
        {
            "log_lines_per_day": np.log1p(lines.mean(axis=1)),
            "log_units_per_day": np.log1p(mean_units),
            "sale_day_share": sale_days / days,
            "log_cv_daily": np.log1p(np.minimum(cv(units), 20)),
            "log_cv_weekly": np.log1p(np.minimum(cv(weeks), 20)),
            "trend": np.log(
                (units[:, -third:].mean(axis=1) + 0.1) / (units[:, :third].mean(axis=1) + 0.1)
            ),
            "log_units_per_line": np.log1p(units.sum(axis=1) / np.maximum(lines.sum(axis=1), 1)),
            "log_mean_gap_days": np.log1p(gaps),
        }
    )
    return SCHEMA.validate(frame)


def picks_per_day(movement: Movement, start: int, end: int) -> np.ndarray:
    """Order lines (picks) per day per product in a period: what the classes should predict."""
    return movement.lines[:, start : end + 1].mean(axis=1)


def order_classes(labels: np.ndarray, activity: np.ndarray) -> np.ndarray:
    """Rename cluster numbers to 0 = slow, 1 = medium, 2 = fast by their average activity
    (e.g. log lines per day); clusters are unordered otherwise."""
    clusters = np.unique(labels)
    means = [activity[labels == c].mean() for c in clusters]
    rank = {c: r for r, c in enumerate(clusters[np.argsort(means)])}
    ordered = np.array([rank[c] for c in labels])
    if len(clusters) < 3:  # fewer groups found: map to the top classes
        ordered = ordered + (3 - len(clusters))
    return ordered
