"""Reorder baseline: the reorder-point formula.

The classic rule (and the one the simulated purchasing team uses): reorder when the
stock position (available + on order) falls to the reorder point

    reorder point = average daily demand (last 28 days) x (lead time + SAFETY_DAYS)

As a risk score: ROP / (ROP + position), which is 0.5 exactly at the reorder point,
rises towards 1 as the position falls below it and towards 0 when stock is plentiful.
It ignores seasons, trends and supplier reliability: the room the models can use.
"""

import numpy as np

SAFETY_DAYS = 8


def reorder_point(demand_28: np.ndarray, lead_days: np.ndarray) -> np.ndarray:
    return np.asarray(demand_28, float) * (np.asarray(lead_days, float) + SAFETY_DAYS)


def reorder_point_score(
    demand_28: np.ndarray, lead_days: np.ndarray, position: np.ndarray
) -> np.ndarray:
    rop = reorder_point(demand_28, lead_days)
    position = np.maximum(np.asarray(position, float), 0)
    return np.where(rop + position > 0, rop / np.maximum(rop + position, 1e-9), 0.0)
