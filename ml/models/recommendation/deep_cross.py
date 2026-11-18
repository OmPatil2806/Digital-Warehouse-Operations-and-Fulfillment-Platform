"""Deep & Cross for recommendation: query and candidate features (embeddings of basket,
history, customer, candidate and its category) go through cross layers, which learn
explicit feature combinations, and a deep network side by side."""

import keras

from models.delay_prediction.deep_cross import CrossLayer
from models.recommendation.common import candidate_input, query_inputs, query_vector


def build(shapes: dict, params: dict, learning_rate: float) -> keras.Model:
    width = params.get("embedding", 16)
    x = {**query_inputs(), "candidate": candidate_input()}
    items = keras.layers.Embedding(shapes["products"] + 1, width)
    customers = keras.layers.Embedding(shapes["customers"] + 1, width)
    x0 = keras.layers.Concatenate()([query_vector(x, items, customers), items(x["candidate"])])
    cross = x0
    for _ in range(params.get("cross_layers", 2)):
        cross = CrossLayer()([x0, cross])
    deep = x0
    for units in params.get("units", [64, 32]):
        deep = keras.layers.Dense(units, activation="relu")(deep)
    output = keras.layers.Dense(1, activation="sigmoid", name="score")(
        keras.layers.Concatenate()([cross, deep])
    )
    model = keras.Model(x, output, name="deep_cross")
    model.compile(optimizer=keras.optimizers.Adam(learning_rate), loss="binary_crossentropy")
    return model
