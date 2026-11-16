"""Inputs and compile settings shared by the stockout networks."""

import keras
import numpy as np


def inputs(shapes: dict[str, tuple[int, ...]]):
    return {name: keras.Input(shape, name=name) for name, shape in shapes.items()}


def normalized(layer_input, train_values: np.ndarray):
    """Standardise numeric inputs with the training mean and spread (saved in the model)."""
    norm = keras.layers.Normalization(axis=-1)
    norm.adapt(train_values)
    return norm(layer_input)


def mlp(x, units: list[int], dropout: float):
    for width in units:
        x = keras.layers.Dense(width, activation="relu")(x)
        if dropout:
            x = keras.layers.Dropout(dropout)(x)
    return x


def compile_model(model: keras.Model, learning_rate: float) -> keras.Model:
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate),
        loss="binary_crossentropy",
        metrics=[keras.metrics.AUC(curve="PR", name="pr_auc")],
    )
    return model
