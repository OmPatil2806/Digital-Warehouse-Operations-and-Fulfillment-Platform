"""Inputs and normalisation shared by the suitability networks."""

import keras
import numpy as np


def inputs(shapes: dict[str, tuple[int, ...]], names: tuple[str, ...]):
    return {name: keras.Input(shapes[name], name=name) for name in names}


def normalized(layer_input, values: np.ndarray):
    norm = keras.layers.Normalization(axis=-1)
    norm.adapt(values)
    return norm(layer_input)


def mlp(x, units: list[int], dropout: float):
    for width in units:
        x = keras.layers.Dense(width, activation="relu")(x)
        if dropout:
            x = keras.layers.Dropout(dropout)(x)
    return x


def compile_model(model: keras.Model, learning_rate: float) -> keras.Model:
    """Regression of log(1 + seconds of picking per day)."""
    model.compile(optimizer=keras.optimizers.Adam(learning_rate), loss="mse", metrics=["mae"])
    return model
