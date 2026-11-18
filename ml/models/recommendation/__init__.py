"""Recommendation networks: Neural Collaborative Filtering, Two-Tower retrieval, Deep &
Cross and a GRU over the customer's purchase sequence. Each scores every product for a
query (basket so far, customer, purchase history)."""

from models.recommendation import deep_cross, gru_sequential, ncf, two_tower

ARCHITECTURES = {
    "ncf": ncf.build,
    "two_tower": two_tower.build,
    "deep_cross": deep_cross.build,
    "gru_sequential": gru_sequential.build,
}
# How each network is trained: "softmax" over the whole catalogue, or "pointwise"
# (one candidate at a time, with sampled negatives).
TRAINING = {
    "ncf": "pointwise",
    "two_tower": "softmax",
    "deep_cross": "pointwise",
    "gru_sequential": "softmax",
}
