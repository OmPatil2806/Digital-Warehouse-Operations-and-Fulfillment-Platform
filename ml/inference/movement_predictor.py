"""Movement classes: fast, medium or slow, from each product's most recent days."""

import numpy as np
from sqlalchemy import Engine

from baselines.movement import abc_classes
from feature_engineering.movement_features import (
    CLASSES,
    FEATURES,
    build_movement,
    movement_features,
    picks_per_day,
)
from inference.common import Context


def predict(engine: Engine, ctx: Context) -> list[dict]:
    movement = build_movement(engine, ctx.first, ctx.last)
    recent = int(ctx.params.get("recent_days", 90))
    start, end = movement.days - recent, movement.days - 1
    picks = picks_per_day(movement, start, end)
    if ctx.is_baseline:
        classes = abc_classes(picks)
    else:
        columns = list(ctx.params.get("columns", FEATURES))
        raw = movement_features(movement, start, end)[columns].to_numpy("float32")
        clusters = ctx.keras_model().predict(raw, verbose=0).argmax(axis=1)
        mapping = ctx.params.get("class_of_cluster", {})
        classes = np.array([CLASSES.index(mapping.get(str(c), "slow")) for c in clusters])
    return [
        {
            "product_id": int(product_id),
            "movement_class": CLASSES[int(c)],
            "picks_per_day": float(picks[i]),
        }
        for i, (product_id, c) in enumerate(zip(movement.product_ids, classes, strict=True))
    ]
