"""Risk levels and the main reasons for a delay prediction.

Reasons use occlusion, as for reorder recommendations: each factor's numbers are set to
their training average one at a time; the larger the drop in delay probability, the
more that factor contributes. Shown only above MIN_CONTRIBUTION.
"""

from collections.abc import Callable

import numpy as np

from feature_engineering.delay_features import NUMERIC

HIGH_RISK = 0.5
MIN_CONTRIBUTION = 0.02
FACTORS = {
    "Large order": ("log_units", "log_lines", "log_weight_kg", "package_count", "log_value"),
    "Waited for stock": ("waited_for_stock", "log_hours_to_dispatch"),
    "Unreliable carrier": ("carrier_late_rate",),
    "Busy warehouse": ("warehouse_fill",),
    "Peak season": ("peak_season", "month_sin", "month_cos"),
    "Short promised transit": ("transit_days",),
}

Predict = Callable[[dict[str, np.ndarray]], np.ndarray]


def risk_level(probability: float, threshold: float) -> str:
    if probability >= max(HIGH_RISK, threshold):
        return "high"
    return "medium" if probability >= threshold else "low"


def reasons(
    predict: Predict, inputs: dict[str, np.ndarray], train_means: np.ndarray, top: int = 3
) -> list[tuple[str, ...]]:
    """The main factors raising each row's delay probability, strongest first."""
    base = predict(inputs)
    effects = {}
    for factor, columns in FACTORS.items():
        numeric = inputs["numeric"].copy()
        for column in columns:
            numeric[:, NUMERIC.index(column)] = train_means[NUMERIC.index(column)]
        effects[factor] = base - predict({**inputs, "numeric": numeric})
    names = list(effects)
    matrix = np.stack([effects[n] for n in names], axis=1)
    out = []
    for row in matrix:
        order = np.argsort(-row, kind="stable")[:top]
        out.append(tuple(names[i] for i in order if row[i] >= MIN_CONTRIBUTION))
    return out
