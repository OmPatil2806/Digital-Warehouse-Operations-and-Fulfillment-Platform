"""Wide & Deep suitability network: the deep part as in the dense network, plus a linear
"wide" part on crosses (pick speed x distance band, heavy x shelf level) that captures
the simple slotting rules directly."""

import keras

from models.slotting.common import compile_model, inputs, mlp, normalized


def build(shapes: dict, params: dict, learning_rate: float, train: dict) -> keras.Model:
    x = inputs(shapes, ("product", "bin", "categorical", "wide"))
    deep_in = keras.layers.Concatenate()(
        [
            normalized(x["product"], train["product"]),
            normalized(x["bin"], train["bin"]),
            x["categorical"],
        ]
    )
    deep = keras.layers.Dense(1)(
        mlp(deep_in, params.get("units", [64, 64, 32]), params.get("dropout", 0.0))
    )
    wide = keras.layers.Dense(1)(x["wide"])
    output = keras.layers.Add(name="log_seconds_per_day")([deep, wide])
    return compile_model(keras.Model(x, output, name="wide_deep_suitability"), learning_rate)
