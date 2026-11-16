"""CNN-LSTM: convolutions first pick up short patterns (a week's rhythm, bursts), then an
LSTM reads the sequence of those patterns."""

import keras

from models.demand_forecasting.common import compile_model, forecast_head, inputs


def build(shapes: dict[str, int], params: dict, learning_rate: float) -> keras.Model:
    history, future, static = inputs(**shapes)
    x = history
    for _ in range(params.get("conv_layers", 2)):
        x = keras.layers.Conv1D(
            params.get("filters", 32),
            params.get("kernel_size", 7),
            padding="causal",
            activation="relu",
        )(x)
    x = keras.layers.MaxPooling1D(params.get("pool", 2))(x)
    encoded = keras.layers.LSTM(params.get("units", 32))(x)
    output = forecast_head(
        encoded,
        future,
        static,
        shapes["horizon"],
        hidden=params.get("hidden", 64),
        dropout=params.get("dropout", 0.1),
    )
    model = keras.Model([history, future, static], output, name="cnn_lstm")
    return compile_model(model, learning_rate)
