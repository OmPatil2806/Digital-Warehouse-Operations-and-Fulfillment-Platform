"""GRU sequential recommender: reads the customer's earlier purchases and then the basket
so far as one sequence, and predicts the next product over the whole catalogue."""

import keras

from models.recommendation.common import query_inputs


def build(shapes: dict, params: dict, learning_rate: float) -> keras.Model:
    x = query_inputs()
    sequence = keras.layers.Concatenate(axis=1)([x["history"], x["context"]])
    embedded = keras.layers.Embedding(
        shapes["products"] + 1, params.get("embedding", 32), mask_zero=True
    )(sequence)
    state = keras.layers.GRU(params.get("gru_units", 64))(embedded)
    customer = keras.layers.Embedding(shapes["customers"] + 1, params.get("embedding", 32))(
        x["customer"]
    )
    joined = keras.layers.Concatenate()([state, customer])
    logits = keras.layers.Dense(shapes["products"] + 1, name="scores")(joined)
    model = keras.Model(x, logits, name="gru_sequential")
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate),
        loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
    )
    return model
