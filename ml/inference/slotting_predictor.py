"""Slotting recommendations: a better pick-face bin per product and warehouse, planned for
tomorrow with every hard rule respected. Stored where the bin changes and picking gets
faster (or the product has no pick location yet)."""

import numpy as np
from sqlalchemy import Engine

from baselines.slotting import abc_cost
from feature_engineering.slotting_features import (
    current_slots,
    pair_features,
    pick_seconds,
    product_state,
)
from inference.common import Context


def predict(engine: Engine, ctx: Context) -> list[dict]:
    from training.train_slotting import Data, plan

    data = Data(engine, ctx.first, ctx.last)
    layout = data.layout
    day = data.days - 1
    state = product_state(data.lines, data.units, day)
    if ctx.is_baseline:

        def cost_maker(w: int):
            return abc_cost(layout, state.picks_90[w])

    else:
        model = ctx.keras_model()
        own = {t.name for t in model.inputs}

        def cost_maker(w: int):
            def cost(products: np.ndarray, bins: np.ndarray) -> np.ndarray:
                x = pair_features(layout, state, w, products, bins)
                inputs = {k: v for k, v in x.items() if k in own}
                return np.expm1(model.predict(inputs, batch_size=65536, verbose=0).ravel())

            return cost

    plans = plan(data, day, {w: cost_maker(w) for w in range(len(layout.warehouse_ids))})
    current = current_slots(engine, layout, ctx.last)
    rows = []
    for assignment in plans:
        w = assignment.warehouse
        for p, b in zip(assignment.products, assignment.bins, strict=True):
            if b < 0:
                continue
            old = current.get((w, int(p)))
            rate, per_pick = state.picks_28[w, p], state.units_per_pick[w, p]
            new_seconds = float(
                rate * pick_seconds(layout, np.array([p]), np.array([b]), per_pick)[0]
            )
            old_seconds = (
                None
                if old is None
                else float(rate * pick_seconds(layout, np.array([p]), np.array([old]), per_pick)[0])
            )
            if old == b or (old_seconds is not None and new_seconds >= old_seconds):
                continue
            rows.append(
                {
                    "product_id": int(layout.product_ids[p]),
                    "warehouse_id": int(layout.warehouse_ids[w]),
                    "current_bin_id": None if old is None else int(layout.bin_ids[old]),
                    "recommended_bin_id": int(layout.bin_ids[b]),
                    "current_seconds_per_day": old_seconds,
                    "recommended_seconds_per_day": new_seconds,
                }
            )
    return rows
