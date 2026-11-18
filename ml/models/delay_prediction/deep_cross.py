"""Deep & Cross Network (Wang et al., 2017): cross layers multiply the inputs with
themselves layer by layer, x_{l+1} = x_0 * (W x_l + b) + x_l, learning feature
combinations (e.g. large order AND peak season AND busy warehouse) explicitly; a deep
network runs alongside."""

import keras

from models.delay_prediction.common import compile_model, inputs, mlp, tabular


@keras.saving.register_keras_serializable(package="warehouse")
class CrossLayer(keras.layers.Layer):
    def build(self, input_shape) -> None:
        width = input_shape[0][-1]
        self.dense = keras.layers.Dense(width)
        self.dense.build((None, width))

    def call(self, inputs):
        x0, x = inputs
        return x0 * self.dense(x) + x


def build(shapes: dict, params: dict, learning_rate: float, train: dict) -> keras.Model:
    x = inputs(shapes, ("numeric", "categorical"))
    x0 = tabular(x, train)
    cross = x0
    for _ in range(params.get("cross_layers", 2)):
        cross = CrossLayer()([x0, cross])
    deep = mlp(x0, params.get("units", [64, 32]), params.get("dropout", 0.1))
    joined = keras.layers.Concatenate()([cross, deep])
    output = keras.layers.Dense(1, activation="sigmoid", name="late")(joined)
    return compile_model(keras.Model(x, output, name="deep_cross"), learning_rate)
