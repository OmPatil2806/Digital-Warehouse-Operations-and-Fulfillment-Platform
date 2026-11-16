"""LSTM: a recurrent network reads the history day by day and keeps a memory of it."""

import keras

from models.demand_forecasting.common import compile_model, forecast_head, inputs


def build(shapes: dict[str, int], params: dict, learning_rate: float) -> keras.Model:
    history, future, static = inputs(**shapes)
    encoded = keras.layers.LSTM(params.get("units", 32))(history)
    output = forecast_head(
        encoded,
        future,
        static,
        shapes["horizon"],
        hidden=params.get("hidden", 64),
        dropout=params.get("dropout", 0.1),
    )
    model = keras.Model([history, future, static], output, name="lstm")
    return compile_model(model, learning_rate)
