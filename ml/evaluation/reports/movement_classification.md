# Movement classification: method comparison

- Dataset: `orders499179-to2026-11-10-d109f294`, training run `20261116-1529`
- Split: train 2024-11-11 to 2026-06-13 (580 days), validation to 2026-08-12 (60), test to 2026-11-10 (90)
- Each method learns its groups on the training period, classifies products from their most recent 90 days and is judged on the **test** period that follows.
- `selection_score` = silhouette when the groups are usable, otherwise -1: in business order (`order_ok`: fast > medium > slow in next-period picks), stable (`stability` >= 0.7 across seeds) and with a fast class carrying at least 50% of the next period's picks (`fast_pick_share`). `persistence`: share of products keeping their training-period class.

| Method | Type | selection_score | silhouette | davies_bouldin | stability | order_ok | rank_correlation | fast_pick_share | persistence | share_fast | share_medium | share_slow | Time |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **abc** (selected) | baseline | 0.285 | 0.285 | 0.886 | 1.000 | 1.000 | 0.888 | 0.785 | 0.875 | 0.410 | 0.296 | 0.293 | 0 s |
| autoencoder_kmeans | Keras + clustering | -1.000 | 0.381 | 0.825 | 0.410 | 1.000 | 0.862 | 0.614 | 0.854 | 0.258 | 0.465 | 0.278 | 44 s |
| vae_kmeans | Keras + clustering | -1.000 | 0.344 | 1.325 | 0.958 | 1.000 | 0.783 | 0.132 | 0.904 | 0.071 | 0.488 | 0.441 | 24 s |
| dec | Keras + clustering | -1.000 | 0.316 | 0.932 | 0.658 | 1.000 | 0.855 | 0.669 | 0.839 | 0.338 | 0.312 | 0.350 | 46 s |

**Selection:** no model beat the baseline abc (selection_score 0.2848 on the test period).
