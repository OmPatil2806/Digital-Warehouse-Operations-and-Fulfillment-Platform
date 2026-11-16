"""Transformer encoder: self-attention lets every day of the history look at every other
day directly (e.g. the same weekday weeks ago), instead of passing a memory along."""

import keras

from models.demand_forecasting.common import compile_model, forecast_head, inputs


@keras.saving.register_keras_serializable(package="warehouse")
class PositionEmbedding(keras.layers.Layer):
    """Adds a learned vector per position, so attention knows the order of the days."""

    def __init__(self, length: int, width: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.length, self.width = length, width
        self.embedding = keras.layers.Embedding(length, width)

    def call(self, x):
        positions = keras.ops.arange(self.length)
        return x + self.embedding(positions)

    def get_config(self) -> dict:
        return {**super().get_config(), "length": self.length, "width": self.width}


def build(shapes: dict[str, int], params: dict, learning_rate: float) -> keras.Model:
    history, future, static = inputs(**shapes)
    width = params.get("width", 32)
    dropout = params.get("dropout", 0.1)
    x = keras.layers.Dense(width)(history)
    x = PositionEmbedding(shapes["window"], width)(x)
    for _ in range(params.get("blocks", 2)):
        attention = keras.layers.MultiHeadAttention(
            num_heads=params.get("heads", 4), key_dim=width // params.get("heads", 4)
        )(x, x)
        x = keras.layers.LayerNormalization()(x + keras.layers.Dropout(dropout)(attention))
        feed = keras.layers.Dense(width * 2, activation="relu")(x)
        feed = keras.layers.Dense(width)(feed)
        x = keras.layers.LayerNormalization()(x + keras.layers.Dropout(dropout)(feed))
    encoded = keras.layers.GlobalAveragePooling1D()(x)
    output = forecast_head(
        encoded, future, static, shapes["horizon"], hidden=params.get("hidden", 64), dropout=dropout
    )
    model = keras.Model([history, future, static], output, name="transformer")
    return compile_model(model, learning_rate)
