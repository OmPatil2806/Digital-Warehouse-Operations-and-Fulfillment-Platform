"""Constrained assignment of products to bins (used by every slotting method).

Each product of a warehouse gets one pick-face bin. Hard rules, never broken:

- zone: cold goods only in cold bins, hazardous only in hazardous bins, other goods in
  picking or bulk bins (never the returns zone);
- capacity: the pick faces in a bin together fit its weight and volume limits.

The method's cost (seconds per day for each product in each bin, lower is better)
decides everything else. Greedy: the products that can save the most (largest gap
between their worst and best allowed bin) choose first and take their cheapest bin
that still has room. One improvement pass then moves each product to a cheaper bin
when room has become available. Products that fit nowhere stay unplaced (reported as
violations).
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from feature_engineering.slotting_features import Layout

# (product rows, bin rows) of equal length -> cost of each pair; called once per warehouse
CostFunction = Callable[[np.ndarray, np.ndarray], np.ndarray]


@dataclass
class Assignment:
    warehouse: int  # index into layout.warehouse_ids
    products: np.ndarray  # product rows
    bins: np.ndarray  # bin row per product, -1 = could not be placed
    need_kg: np.ndarray
    need_cm3: np.ndarray

    def as_dict(self) -> dict[int, int]:
        return {int(p): int(b) for p, b in zip(self.products, self.bins, strict=True)}


def assign(
    layout: Layout,
    warehouse: int,
    products: np.ndarray,
    cost: CostFunction,
    need_kg: np.ndarray,
    need_cm3: np.ndarray,
    *,
    improve: bool = True,
) -> Assignment:
    in_wh = np.flatnonzero(layout.bin_warehouse == layout.warehouse_ids[warehouse])
    free_kg = layout.bin_max_kg[in_wh].astype(float).copy()
    free_cm3 = layout.bin_max_cm3[in_wh].astype(float).copy()
    allowed = (
        np.stack([layout.allowed(p)[in_wh] for p in products])
        if len(products)
        else (np.zeros((0, len(in_wh)), bool))
    )
    rows, cols = np.nonzero(allowed)  # every allowed (product, bin) pair, scored at once
    matrix = np.full(allowed.shape, np.inf)
    if len(rows):
        matrix[rows, cols] = cost(np.asarray(products)[rows], in_wh[cols])
    costs = list(matrix)
    spread = np.array([np.ptp(r[np.isfinite(r)]) if np.isfinite(r).any() else -1.0 for r in costs])
    chosen = np.full(len(products), -1)
    for i in np.argsort(-spread, kind="stable"):
        fits = np.isfinite(costs[i]) & (free_kg >= need_kg[i]) & (free_cm3 >= need_cm3[i])
        if fits.any():
            j = int(np.argmin(np.where(fits, costs[i], np.inf)))
            chosen[i] = j
            free_kg[j] -= need_kg[i]
            free_cm3[j] -= need_cm3[i]
    if improve:
        for i in np.argsort(-spread, kind="stable"):
            j = chosen[i]
            if j < 0:
                continue
            fits = np.isfinite(costs[i]) & (free_kg >= need_kg[i]) & (free_cm3 >= need_cm3[i])
            fits[j] = False
            if fits.any():
                k = int(np.argmin(np.where(fits, costs[i], np.inf)))
                if costs[i][k] < costs[i][j]:
                    free_kg[j] += need_kg[i]
                    free_cm3[j] += need_cm3[i]
                    free_kg[k] -= need_kg[i]
                    free_cm3[k] -= need_cm3[i]
                    chosen[i] = k
    bins = np.where(chosen >= 0, in_wh[np.maximum(chosen, 0)], -1)
    return Assignment(warehouse, np.asarray(products), bins, need_kg, need_cm3)


def violations(layout: Layout, assignment: Assignment) -> dict[str, int]:
    """Broken rules of an assignment: must all be 0."""
    placed = assignment.bins >= 0
    zone = sum(
        not layout.allowed(p)[b]
        for p, b in zip(assignment.products[placed], assignment.bins[placed], strict=True)
    )
    wrong_wh = int(
        np.sum(
            layout.bin_warehouse[assignment.bins[placed]]
            != layout.warehouse_ids[assignment.warehouse]
        )
    )
    load_kg = np.bincount(assignment.bins[placed], assignment.need_kg[placed], len(layout.bin_ids))
    load_cm3 = np.bincount(
        assignment.bins[placed], assignment.need_cm3[placed], len(layout.bin_ids)
    )
    return {
        "zone": int(zone) + wrong_wh,
        "overweight": int(np.sum(load_kg > layout.bin_max_kg + 1e-6)),
        "overvolume": int(np.sum(load_cm3 > layout.bin_max_cm3 + 1e-6)),
        "unplaced": int(np.sum(~placed)),
    }
