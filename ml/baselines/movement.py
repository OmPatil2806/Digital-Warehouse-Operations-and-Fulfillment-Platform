"""Movement baseline: ABC analysis by picks.

Products are ranked by order lines (picks) per day; the ones that together make the first
80 % of all picks are A (fast), the next 15 % B (medium), the rest C (slow). One number,
no learning: the classic warehouse rule.
"""

import numpy as np

A_SHARE, B_SHARE = 0.80, 0.95


def abc_classes(picks_per_day: np.ndarray) -> np.ndarray:
    """0 = slow (C), 1 = medium (B), 2 = fast (A) for each product."""
    picks = np.asarray(picks_per_day, float)
    if picks.ndim != 1 or len(picks) == 0:
        raise ValueError("one pick rate per product is needed")
    total = picks.sum()
    if total <= 0:
        return np.zeros(len(picks), int)
    order = np.argsort(-picks, kind="stable")
    before = (np.cumsum(picks[order]) - picks[order]) / total  # share before this product
    ranked = np.where(before < A_SHARE, 2, np.where(before < B_SHARE, 1, 0))
    classes = np.empty(len(picks), int)
    classes[order] = ranked
    return classes
