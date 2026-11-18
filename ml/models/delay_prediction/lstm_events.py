"""LSTM on order events: reads the order's status history up to dispatch (which status,
how many hours after the order) and combines it with the dispatch-time numbers."""

import keras

from models.delay_prediction.common import compile_model, inputs, mlp, tabular


def build(shapes: dict, params: dict, learning_rate: float, train: dict) -> keras.Model:
    x = inputs(shapes, ("numeric", "categorical", "sequence"))
    events = keras.layers.Masking(mask_value=0.0)(x["sequence"])
    events = keras.layers.LSTM(params.get("lstm_units", 32))(events)
    joined = keras.layers.Concatenate()([events, tabular(x, train)])
    hidden = mlp(joined, params.get("units", [64]), params.get("dropout", 0.1))
    output = keras.layers.Dense(1, activation="sigmoid", name="late")(hidden)
    return compile_model(keras.Model(x, output, name="lstm_events"), learning_rate)
