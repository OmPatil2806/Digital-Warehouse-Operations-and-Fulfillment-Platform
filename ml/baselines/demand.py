"""Demand forecasting baselines: moving average and seasonal naive.

Both forecast from the window of past daily demand only and give a low-high range
(10th and 90th percentile) besides the point forecast, like the neural models.
Output shape: (n, horizon, 3) with columns low, point, high.
"""

import numpy as np

QUANTILES = (0.1, 0.5, 0.9)


def moving_average(history: np.ndarray, horizon: int, days: int = 28) -> np.ndarray:
    """Every forecast day = the average of the last `days`; range from those days' spread."""
    recent = _recent(history, days)
    point = recent.mean(axis=1)
    low, high = np.quantile(recent, [QUANTILES[0], QUANTILES[2]], axis=1)
    return _stack(low, point, high, horizon)


def seasonal_naive(history: np.ndarray, horizon: int, weeks: int = 4) -> np.ndarray:
    """Each forecast day = the same weekday last week; range from the last `weeks` of that
    weekday."""
    recent = _recent(history, 7 * weeks)
    by_weekday = recent.reshape(len(recent), weeks, 7)  # (n, week, weekday position)
    point = np.tile(recent[:, -7:], (1, -(-horizon // 7)))[:, :horizon]
    low7, high7 = np.quantile(by_weekday, [QUANTILES[0], QUANTILES[2]], axis=1)
    low = np.tile(low7, (1, -(-horizon // 7)))[:, :horizon]
    high = np.tile(high7, (1, -(-horizon // 7)))[:, :horizon]
    return np.stack([np.minimum(low, point), point, np.maximum(high, point)], axis=2)


BASELINES = {"moving_average": moving_average, "seasonal_naive": seasonal_naive}


def _recent(history: np.ndarray, days: int) -> np.ndarray:
    values = np.asarray(history, dtype="float32")
    if values.ndim != 2 or values.shape[1] < days:
        raise ValueError(f"need (n, >= {days}) days of history, got {values.shape}")
    return values[:, -days:]


def _stack(low: np.ndarray, point: np.ndarray, high: np.ndarray, horizon: int) -> np.ndarray:
    columns = [np.repeat(v[:, None], horizon, axis=1) for v in (low, point, high)]
    return np.stack(columns, axis=2).astype("float32")
