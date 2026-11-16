"""Wide & Deep: a linear "wide" part memorises simple rules (days-of-cover bucket x peak
season, month, category, warehouse) while the "deep" network generalises from the
numbers; their scores are added before the sigmoid."""

import keras

from models.reorder.common import compile_model, inputs, mlp, normalized


def build(shapes: dict, params: dict, learning_rate: float, train: dict) -> keras.Model:
    x = inputs({k: shapes[k] for k in ("numeric", "categorical", "wide")})
    deep_in = keras.layers.Concatenate()(
        [normalized(x["numeric"], train["numeric"]), x["categorical"]]
    )
    deep = mlp(deep_in, params.get("units", [64, 32]), params.get("dropout", 0.1))
    deep_logit = keras.layers.Dense(1, name="deep_logit")(deep)
    wide_in = keras.layers.Concatenate()([x["wide"], x["categorical"]])
    wide_logit = keras.layers.Dense(1, name="wide_logit")(wide_in)
    logit = keras.layers.Add()([deep_logit, wide_logit])
    output = keras.layers.Activation("sigmoid", name="stockout")(logit)
    return compile_model(keras.Model(x, output, name="wide_deep"), learning_rate)
