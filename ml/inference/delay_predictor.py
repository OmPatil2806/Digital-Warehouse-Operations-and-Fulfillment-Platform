"""Delay risk of the shipments still on their way, with risk level and reasons."""

import numpy as np
from sqlalchemy import Engine

from baselines.delay import LogisticBaseline
from feature_engineering.delay_features import build_delay_set
from inference.common import Context
from models.delay_prediction.explain import reasons, risk_level
from training.data import read_frame


def predict(engine: Engine, ctx: Context) -> list[dict]:
    from training.train_delay import model_inputs

    as_of = ctx.last if ctx.backtest else None  # a backtest sees the data as on that day
    on_the_way = build_delay_set(engine, on_the_way=True, as_of=as_of)
    if not len(on_the_way):
        return []
    delivered = build_delay_set(engine, as_of=as_of)
    if ctx.is_baseline:  # the regression is refitted on the training period, as in training
        train_end = np.datetime64(ctx.split().train_end, "D")
        past = delivered.subset(np.flatnonzero(delivered.shipped_day <= train_end))
        baseline = LogisticBaseline(int(ctx.params.get("seed", 0))).fit(
            past.inputs()["numeric"], past.categorical, past.label
        )
        scorer = baseline.predict
    else:
        model = ctx.keras_model()

        def scorer(inputs: dict) -> np.ndarray:
            return model.predict(model_inputs(model, inputs), batch_size=8192, verbose=0).ravel()

    probability = np.clip(scorer(on_the_way.inputs()), 0, 1)
    why = reasons(scorer, on_the_way.inputs(), delivered.inputs()["numeric"].mean(axis=0))
    threshold = ctx.threshold()
    shipments = read_frame(engine, "SELECT order_id, id FROM shipments").set_index("order_id")["id"]
    return [
        {
            "order_id": int(order_id),
            "shipment_id": int(shipments[order_id]),
            "probability": float(p),
            "risk_level": risk_level(float(p), threshold),
            "reasons": list(r),
        }
        for order_id, p, r in zip(on_the_way.order_ids, probability, why, strict=True)
    ]
