"""Demand forecasts: expected units for each of the next days per product, with a range."""

from datetime import timedelta

import numpy as np
from sqlalchemy import Engine

from baselines.demand import BASELINES
from feature_engineering.demand_features import build_demand_data, latest_windows, product_scale
from inference.common import Context


def predict(engine: Engine, ctx: Context) -> list[dict]:
    window = int(ctx.params.get("window", 56))
    horizon = int(ctx.params.get("horizon", 30))
    data = build_demand_data(engine, ctx.first, ctx.last)
    train_end = data.day_index(ctx.split().train_end)
    scale = product_scale(data, until=train_end + 1)  # as in training
    windows = latest_windows(data, window=window, horizon=horizon, scale=scale)
    if ctx.is_baseline:
        forecast = BASELINES[ctx.name](windows.raw_history(), horizon)
    else:
        scaled = ctx.keras_model().predict(windows.inputs(), batch_size=4096, verbose=0)
        forecast = scaled * windows.scale[:, None, None]
    forecast = np.maximum(forecast, 0)
    expected = forecast[:, :, 1]
    low = np.minimum(forecast[:, :, 0], expected)
    high = np.maximum(forecast[:, :, 2], expected)
    rows = []
    for p, product_id in enumerate(data.product_ids):
        for h in range(horizon):
            rows.append(
                {
                    "product_id": int(product_id),
                    "day": ctx.last + timedelta(days=h + 1),
                    "expected_units": float(expected[p, h]),
                    "low_units": float(low[p, h]),
                    "high_units": float(high[p, h]),
                }
            )
    return rows
