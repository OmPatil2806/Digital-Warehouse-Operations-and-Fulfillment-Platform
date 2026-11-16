"""Inputs, output head and loss shared by the demand forecasting networks.

The head predicts three values per forecast day: low, expected and high. The low and
high values are the expected value minus/plus a positive gap, so the range can never be
upside down.

The middle value is trained as the *expected* demand (squared error), not the median:
for slow and lumpy products the median day is 0, and a median forecast would add up to
far too little over 7-30 days. The low and high values are trained as the 10 % and 90 %
quantiles (pinball loss), giving an 80 % range.
"""

import keras
from keras import ops

LOW, HIGH = 0.1, 0.9  # quantiles of the range


def inputs(window: int, horizon: int, history_features: int, future_features: int, static: int):
    return (
        keras.Input((window, history_features), name="history"),
        keras.Input((horizon, future_features), name="future"),
        keras.Input((static,), name="static"),
    )


def forecast_head(encoded, future, static, horizon: int, *, hidden: int, dropout: float):
    """Encoded history + calendar of the forecast days + product info -> (horizon, 3)."""
    x = keras.layers.Concatenate()([encoded, keras.layers.Flatten()(future), static])
    x = keras.layers.Dense(hidden, activation="relu")(x)
    if dropout:
        x = keras.layers.Dropout(dropout)(x)
    middle = keras.layers.Dense(horizon, name="middle")(x)
    below = keras.layers.Dense(horizon, activation="softplus", name="gap_low")(x)
    above = keras.layers.Dense(horizon, activation="softplus", name="gap_high")(x)
    low = keras.layers.Subtract()([middle, below])
    high = keras.layers.Add()([middle, above])
    columns = [keras.layers.Reshape((horizon, 1))(v) for v in (low, middle, high)]
    return keras.layers.Concatenate(axis=-1, name="quantiles")(columns)


def pinball(y_true, y_pred, q: float):
    error = y_true - y_pred
    return ops.mean(ops.maximum(q * error, (q - 1) * error))


@keras.saving.register_keras_serializable(package="warehouse")
def forecast_loss(y_true, y_pred):
    """Squared error for the expected value + pinball loss for the low and high values."""
    y_true = ops.cast(y_true, y_pred.dtype)
    expected = ops.mean(ops.square(y_true - y_pred[..., 1]))
    return expected + pinball(y_true, y_pred[..., 0], LOW) + pinball(y_true, y_pred[..., 2], HIGH)


def compile_model(model: keras.Model, learning_rate: float) -> keras.Model:
    model.compile(optimizer=keras.optimizers.Adam(learning_rate), loss=forecast_loss)
    return model
