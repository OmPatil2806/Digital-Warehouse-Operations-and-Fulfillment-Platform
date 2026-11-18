# Slotting: method comparison

- Dataset: `orders499179-to2026-11-10-d109f294`, training run `20261118-0807`
- Split: train 2024-11-11 to 2026-06-13 (580 days), validation to 2026-08-12 (60), test to 2026-11-10 (90); 793,768 training pairs
- Each method plans one pick-face bin per product and warehouse on the last day before the **test** period; it is judged with the real picks of the test period against the current layout (where the products were), which needs 61.6 picking hours per day (estimated pick time model, see feature_engineering/slotting_features.py).
- Hard rules (zone, weight, volume, every product placed) must have 0 violations; the selection uses the pick-time reduction.

| Method | Type | pick_time_reduction | distance_reduction | pick_hours_per_day_after | violations | bins_used_share | mean_volume_fill | moved_share | Time |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| current layout | reference | 0.000 | 0.000 | 61.592 | 48.000 | 0.550 | 0.179 | 0.000 | - |
| perfect foresight (upper bound) | reference | 0.501 | 0.612 | 30.671 | 0.000 | 0.154 | 0.978 | 0.998 | - |
| **dense_suitability** (selected) | Keras + optimizer | 0.498 | 0.609 | 30.849 | 0.000 | 0.159 | 0.950 | 0.999 | 25 s |
| wide_deep_suitability | Keras + optimizer | 0.498 | 0.608 | 30.867 | 0.000 | 0.161 | 0.938 | 0.999 | 31 s |
| abc_slotting | baseline | 0.497 | 0.607 | 30.942 | 0.000 | 0.155 | 0.976 | 0.999 | 4 s |

**Selection:** dense_suitability beat the baseline abc_slotting: selection_score 0.4984 vs 0.4969 on the test period.
