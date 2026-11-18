"""Wide & Deep: a linear part on rule-like crosses (carrier x peak season, waited for
stock x priority, warehouse fill band) plus the deep network; scores are added."""

import keras

from models.delay_prediction.common import compile_model, inputs, mlp, tabular


def build(shapes: dict, params: dict, learning_rate: float, train: dict) -> keras.Model:
    x = inputs(shapes, ("numeric", "categorical", "wide"))
    deep = mlp(tabular(x, train), params.get("units", [64, 32]), params.get("dropout", 0.1))
    logit = keras.layers.Add()(
        [
            keras.layers.Dense(1)(deep),
            keras.layers.Dense(1)(keras.layers.Concatenate()([x["wide"], x["categorical"]])),
        ]
    )
    output = keras.layers.Activation("sigmoid", name="late")(logit)
    return compile_model(keras.Model(x, output, name="wide_deep"), learning_rate)
