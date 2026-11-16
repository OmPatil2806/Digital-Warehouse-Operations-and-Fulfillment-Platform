"""LSTM stockout model: reads the last weeks of demand and available stock day by day,
then combines that with the snapshot's numbers."""

import keras

from models.reorder.common import compile_model, inputs, mlp, normalized


def build(shapes: dict, params: dict, learning_rate: float, train: dict) -> keras.Model:
    x = inputs({k: shapes[k] for k in ("numeric", "categorical", "sequence")})
    sequence = keras.layers.LSTM(params.get("lstm_units", 32))(
        normalized(x["sequence"], train["sequence"])
    )
    joined = keras.layers.Concatenate()(
        [sequence, normalized(x["numeric"], train["numeric"]), x["categorical"]]
    )
    hidden = mlp(joined, params.get("units", [64]), params.get("dropout", 0.1))
    output = keras.layers.Dense(1, activation="sigmoid", name="stockout")(hidden)
    return compile_model(keras.Model(x, output, name="lstm"), learning_rate)
