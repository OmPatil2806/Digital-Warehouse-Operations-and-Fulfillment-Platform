"""Dense suitability network: product history + bin position -> expected seconds of
picking per day for that product in that bin (as log(1 + seconds))."""

import keras

from models.slotting.common import compile_model, inputs, mlp, normalized


def build(shapes: dict, params: dict, learning_rate: float, train: dict) -> keras.Model:
    x = inputs(shapes, ("product", "bin", "categorical"))
    joined = keras.layers.Concatenate()(
        [
            normalized(x["product"], train["product"]),
            normalized(x["bin"], train["bin"]),
            x["categorical"],
        ]
    )
    hidden = mlp(joined, params.get("units", [64, 64, 32]), params.get("dropout", 0.0))
    output = keras.layers.Dense(1, name="log_seconds_per_day")(hidden)
    return compile_model(keras.Model(x, output, name="dense_suitability"), learning_rate)
