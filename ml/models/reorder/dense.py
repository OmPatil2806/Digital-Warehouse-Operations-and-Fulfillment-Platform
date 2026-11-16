"""Dense network on the snapshot's numbers and its category/warehouse."""

import keras

from models.reorder.common import compile_model, inputs, mlp, normalized


def build(shapes: dict, params: dict, learning_rate: float, train: dict) -> keras.Model:
    x = inputs({k: shapes[k] for k in ("numeric", "categorical")})
    joined = keras.layers.Concatenate()(
        [normalized(x["numeric"], train["numeric"]), x["categorical"]]
    )
    hidden = mlp(joined, params.get("units", [64, 32]), params.get("dropout", 0.1))
    output = keras.layers.Dense(1, activation="sigmoid", name="stockout")(hidden)
    return compile_model(keras.Model(x, output, name="dense"), learning_rate)
