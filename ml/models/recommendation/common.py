"""Layers and helpers shared by the recommendation networks."""

import keras
import numpy as np
from keras import ops

from feature_engineering.interaction_features import MAX_CONTEXT, MAX_HISTORY


@keras.saving.register_keras_serializable(package="warehouse")
class MaskedMean(keras.layers.Layer):
    """Average of the embeddings of the non-padding ids (0 = padding)."""

    def call(self, inputs):
        ids, vectors = inputs
        mask = ops.cast(ops.expand_dims(ids > 0, -1), vectors.dtype)
        return ops.sum(vectors * mask, axis=1) / ops.maximum(ops.sum(mask, axis=1), 1.0)


def query_inputs() -> dict:
    return {
        "context": keras.Input((MAX_CONTEXT,), dtype="int32", name="context"),
        "customer": keras.Input((), dtype="int32", name="customer"),
        "history": keras.Input((MAX_HISTORY,), dtype="int32", name="history"),
    }


def candidate_input():
    return keras.Input((), dtype="int32", name="candidate")


def query_vector(x: dict, items: keras.layers.Embedding, customers: keras.layers.Embedding):
    """Basket average + history average + customer embedding, joined."""
    return keras.layers.Concatenate()(
        [
            MaskedMean()([x["context"], items(x["context"])]),
            MaskedMean()([x["history"], items(x["history"])]),
            customers(x["customer"]),
        ]
    )


def pointwise_inputs(queries: dict[str, np.ndarray], candidates: np.ndarray) -> dict:
    return {**queries, "candidate": candidates.astype("int32")}


def score_pointwise(
    model: keras.Model, inputs: dict[str, np.ndarray], products: int, chunk: int = 128
) -> np.ndarray:
    """(queries, products + 1) scores by scoring every product for every query."""
    n = len(inputs["customer"])
    out = np.full((n, products + 1), -np.inf, "float32")
    candidates = np.arange(1, products + 1, dtype="int32")
    for start in range(0, n, chunk):
        part = {k: v[start : start + chunk] for k, v in inputs.items()}
        size = len(part["customer"])
        tiled = {k: np.repeat(v, products, axis=0) for k, v in part.items()}
        tiled["candidate"] = np.tile(candidates, size)
        scores = model.predict(tiled, batch_size=65536, verbose=0).reshape(size, products)
        out[start : start + size, 1:] = scores
    return out
