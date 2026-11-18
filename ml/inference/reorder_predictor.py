"""Reorder recommendations: products at risk of running out, what to order and why.
Only actionable ones (medium or high priority) are stored."""

import numpy as np
from sqlalchemy import Engine

from baselines.reorder import reorder_point_score
from feature_engineering.reorder_features import NUMERIC, build_stock_history, make_snapshots
from inference.common import Context
from models.reorder.recommend import contributions, recommend


def predict(engine: Engine, ctx: Context) -> list[dict]:
    from training.train_reorder import model_inputs

    history = build_stock_history(engine, ctx.first, ctx.last)
    today = make_snapshots(
        history,
        [history.days - 1],
        horizon=int(ctx.params.get("horizon", 14)),
        sequence_days=int(ctx.params.get("sequence_days", 28)),
    )
    if not len(today):
        return []
    if ctx.is_baseline:

        def scorer(inputs: dict) -> np.ndarray:
            numeric = inputs["numeric"]
            return reorder_point_score(
                np.expm1(numeric[:, NUMERIC.index("log_demand_28")]),
                numeric[:, NUMERIC.index("lead_days")],
                np.expm1(numeric[:, NUMERIC.index("log_position")]),
            )

    else:
        model = ctx.keras_model()

        def scorer(inputs: dict) -> np.ndarray:
            return model.predict(model_inputs(model, inputs), batch_size=8192, verbose=0).ravel()

    probability = scorer(today.inputs())
    # Reasons compare each product with the average product of today.
    effects = contributions(scorer, today, today.numeric.to_numpy("float32").mean(axis=0))
    recommendations = recommend(
        today,
        probability,
        threshold=ctx.threshold(),
        product_ids=history.product_ids,
        warehouse_ids=history.warehouse_ids,
        lead_days=history.lead_days,
        today=ctx.last,
        factor_effects=effects,
    )
    return [
        {
            "product_id": r.product_id,
            "warehouse_id": r.warehouse_id,
            "probability": min(max(r.probability, 0.0), 1.0),
            "priority": r.priority,
            "reorder_date": r.reorder_date,
            "quantity": r.quantity,
            "reasons": list(r.reasons),
        }
        for r in recommendations
        if r.priority != "low"
    ]
