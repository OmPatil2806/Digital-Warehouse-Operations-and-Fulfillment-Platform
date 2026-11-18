"""Slotting: suitability networks score (product, bin) pairs by their expected pick time
per day; optimizer.assign turns the scores into a layout that respects every hard rule."""

from models.slotting import suitability_dense, suitability_wide_deep

ARCHITECTURES = {
    "dense_suitability": suitability_dense.build,
    "wide_deep_suitability": suitability_wide_deep.build,
}
