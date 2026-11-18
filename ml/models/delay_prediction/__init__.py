"""Order-delay networks: Dense, Wide & Deep, Deep & Cross Network and an LSTM over the
order's status events. All output the probability that a shipment arrives late."""

from models.delay_prediction import deep_cross, dense, lstm_events, wide_deep

ARCHITECTURES = {
    "dense": dense.build,
    "wide_deep": wide_deep.build,
    "deep_cross": deep_cross.build,
    "lstm_events": lstm_events.build,
}
