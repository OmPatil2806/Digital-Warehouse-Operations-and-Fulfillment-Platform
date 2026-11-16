"""From stockout probabilities to reorder recommendations a manager can act on.

For each product in each warehouse:

- **priority**: high (probability >= HIGH_RISK), medium (>= the decision threshold chosen
  on the validation period), otherwise low;
- **reorder date**: today for medium and high; otherwise the day the stock position is
  expected to reach the (season-adjusted) reorder point;
- **quantity**: enough to cover lead time + safety days + COVER_DAYS of the expected
  demand (last 28 days x last year's seasonal ratio), minus the stock position; at
  least SAFETY_DAYS of demand when the product is at risk;
- **reasons**: the factors that raise the risk most. Each factor's numbers are set to
  their training average one group at a time; the bigger the drop in probability, the
  more that factor contributes (an occlusion explanation that works for every model).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

import numpy as np

from baselines.reorder import SAFETY_DAYS
from feature_engineering.reorder_features import NUMERIC, Snapshots

HIGH_RISK = 0.6
COVER_DAYS = 21
MIN_CONTRIBUTION = 0.02  # smaller effects are not worth showing

FACTORS = {
    "Low available stock": ("log_available", "log_cover_days"),
    "Little stock on order": ("log_on_order", "log_position", "log_position_cover_days"),
    "Demand rising recently": ("log_demand_7", "trend_7_28"),
    "High or irregular demand": ("log_demand_28", "log_demand_56", "log_demand_std_28"),
    "Seasonal peak ahead": (
        "season_ratio",
        "has_last_year",
        "month_sin",
        "month_cos",
        "peak_season",
    ),
    "Long or unreliable supplier lead time": ("lead_days", "supplier_reliability"),
}

Predict = Callable[[dict[str, np.ndarray]], np.ndarray]


@dataclass(frozen=True)
class Recommendation:
    product_id: int
    warehouse_id: int
    probability: float
    priority: str
    reorder_date: date
    quantity: int
    reasons: tuple[str, ...]


def contributions(
    predict: Predict, snapshots: Snapshots, train_means: np.ndarray
) -> dict[str, np.ndarray]:
    """Per factor: how much the probability drops when that factor is made average."""
    base_inputs = snapshots.inputs()
    base = predict(base_inputs)
    result = {}
    for factor, columns in FACTORS.items():
        changed = dict(base_inputs)
        numeric = base_inputs["numeric"].copy()
        for column in columns:
            index = NUMERIC.index(column)
            numeric[:, index] = train_means[index]
        changed["numeric"] = numeric
        result[factor] = base - predict(changed)
    return result


def priority(probability: float, threshold: float) -> str:
    if probability >= max(HIGH_RISK, threshold):
        return "high"
    return "medium" if probability >= threshold else "low"


def recommend(
    snapshots: Snapshots,
    probabilities: np.ndarray,
    *,
    threshold: float,
    product_ids: np.ndarray,
    warehouse_ids: np.ndarray,
    lead_days: np.ndarray,
    today: date,
    factor_effects: dict[str, np.ndarray] | None = None,
) -> list[Recommendation]:
    """Recommendations for the snapshots of one day, highest risk first."""
    season = np.clip(snapshots.numeric["season_ratio"].to_numpy(), 0.5, 3.0)
    rate = np.maximum(snapshots.demand_28 * season, 0.05)
    lead = lead_days[snapshots.series]
    out = []
    for i in np.argsort(-probabilities, kind="stable"):
        p = float(probabilities[i])
        level = priority(p, threshold)
        reorder_point = rate[i] * (lead[i] + SAFETY_DAYS)
        if level == "low":
            days = int(max(0.0, (snapshots.position[i] - reorder_point) / rate[i]))
            when = today + timedelta(days=min(days, 365))
        else:
            when = today
        target = rate[i] * (lead[i] + SAFETY_DAYS + COVER_DAYS)
        quantity = max(0, ceil(target - snapshots.position[i]))
        if level != "low":  # at risk: order at least a safety buffer
            quantity = max(quantity, ceil(rate[i] * SAFETY_DAYS))
        reasons: tuple[str, ...] = ()
        if factor_effects is not None:
            ranked = sorted(factor_effects.items(), key=lambda item: -item[1][i])
            reasons = tuple(name for name, e in ranked[:3] if e[i] >= MIN_CONTRIBUTION)
        out.append(
            Recommendation(
                product_id=int(product_ids[snapshots.series[i]]),
                warehouse_id=int(warehouse_ids[snapshots.series[i]]),
                probability=p,
                priority=level,
                reorder_date=when,
                quantity=quantity,
                reasons=reasons,
            )
        )
    return out
