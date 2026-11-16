"""Demand forecasting networks: LSTM, GRU, CNN-LSTM and Transformer encoder.

All four read the same inputs (see feature_engineering.demand_features) and end in the
same head (common.forecast_head), so they differ only in how they read the history.
"""

from models.demand_forecasting import cnn_lstm, gru, lstm, transformer

ARCHITECTURES = {
    "lstm": lstm.build,
    "gru": gru.build,
    "cnn_lstm": cnn_lstm.build,
    "transformer": transformer.build,
}
