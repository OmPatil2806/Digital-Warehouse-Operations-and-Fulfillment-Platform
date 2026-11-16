"""Stockout risk networks: Dense, Wide & Deep and an LSTM over the recent stock history.

All read the snapshot inputs of feature_engineering.reorder_features and output the
probability that the product runs out within the horizon. Numeric inputs are
normalised inside the model (a Normalization layer fitted on the training data), so the
saved .keras file contains its own preprocessing.
"""

from models.reorder import dense, lstm_stockout, wide_deep

ARCHITECTURES = {
    "dense": dense.build,
    "wide_deep": wide_deep.build,
    "lstm": lstm_stockout.build,
}
