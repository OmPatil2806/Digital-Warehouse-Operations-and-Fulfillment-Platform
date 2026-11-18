"""Dense network on the dispatch-time numbers and categories."""

import keras

from models.delay_prediction.common import compile_model, inputs, mlp, tabular


def build(shapes: dict, params: dict, learning_rate: float, train: dict) -> keras.Model:
    x = inputs(shapes, ("numeric", "categorical"))
    hidden = mlp(tabular(x, train), params.get("units", [64, 32]), params.get("dropout", 0.1))
    output = keras.layers.Dense(1, activation="sigmoid", name="late")(hidden)
    return compile_model(keras.Model(x, output, name="dense"), learning_rate)
