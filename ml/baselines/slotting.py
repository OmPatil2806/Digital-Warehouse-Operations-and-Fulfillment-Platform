"""Slotting baseline: ABC-based slotting.

The classic rule: the products picked most in the last 90 days go to the bins closest to
packing. As a cost for the shared optimizer: past picks per day x distance, so the
fastest movers have most to gain and choose first; weight and shelf height are ignored.
"""

import numpy as np

from feature_engineering.slotting_features import Layout


def abc_cost(layout: Layout, picks_90: np.ndarray):
    """Cost function (products, bins) -> past picks x distance (+ a tiny level tie-break)."""

    def cost(products: np.ndarray, bins: np.ndarray) -> np.ndarray:
        return (picks_90[products] + 1e-3) * layout.bin_distance[bins] + 1e-6 * layout.bin_level[
            bins
        ]

    return cost
