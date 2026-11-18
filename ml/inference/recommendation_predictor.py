"""Product recommendations: for every product, the products most often added to a
basket that holds it (as for a customer starting a basket with that product)."""

import numpy as np
from sqlalchemy import Engine

from baselines.recommendation import FrequentlyBoughtTogether
from feature_engineering.interaction_features import MAX_CONTEXT, MAX_HISTORY, load_baskets
from inference.common import Context

TOP = 10


def predict(engine: Engine, ctx: Context) -> list[dict]:
    from models.recommendation import TRAINING
    from models.recommendation.common import score_pointwise
    from training.train_recommendation import top_k

    baskets = load_baskets(engine)
    products = baskets.products
    context = np.zeros((products, MAX_CONTEXT), "int32")
    context[:, 0] = np.arange(1, products + 1)
    inputs = {
        "context": context,
        "customer": np.zeros(products, "int32"),  # no particular customer
        "history": np.zeros((products, MAX_HISTORY), "int32"),
    }
    if ctx.is_baseline:
        scores = FrequentlyBoughtTogether().fit(baskets).scores(inputs)
    else:
        model = ctx.keras_model()
        if TRAINING[ctx.name] == "softmax":
            scores = model.predict(inputs, batch_size=4096, verbose=0)
        else:
            scores = score_pointwise(model, inputs, products)
    ranked = top_k(scores, context, TOP)
    ids = baskets.product_ids
    return [
        {
            "product_id": int(ids[q]),
            "recommended_product_id": int(ids[item - 1]),
            "rank": rank,
            "score": float(scores[q, item]),
        }
        for q, items in enumerate(ranked)
        for rank, item in enumerate(items, start=1)
    ]
