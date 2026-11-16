# Reorder recommendation: stockout-risk model comparison

- Dataset: `orders499179-to2026-11-10-d109f294`, training run `20261116-1446`
- Split: train 2024-11-11 to 2026-06-13 (580 days), validation to 2026-08-12 (60), test to 2026-11-10 (90)
- Snapshots (in-stock product x warehouse x day): train 300,000 (9.7% run out within the horizon), validation 40,343 (9.0% run out within the horizon), test 62,785 (10.4% run out within the horizon)
- Metrics on the **test** period. `pr_auc` is used for the selection; precision, recall and F1 at each model's threshold (best F1 on validation); `flagged_share` is the share of snapshots flagged for reordering; `brier` and `ece` measure calibration (lower is better).

| Model | Type | pr_auc | roc_auc | precision | recall | f1 | flagged_share | brier | ece | Epochs | Time |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **lstm** (selected) | Keras | 0.328 | 0.776 | 0.274 | 0.522 | 0.359 | 0.199 | 0.083 | 0.012 | 28 | 349 s |
| wide_deep | Keras | 0.319 | 0.775 | 0.278 | 0.491 | 0.355 | 0.184 | 0.083 | 0.009 | 29 | 46 s |
| dense | Keras | 0.313 | 0.775 | 0.289 | 0.464 | 0.356 | 0.168 | 0.083 | 0.005 | 30 | 45 s |
| reorder_point | baseline | 0.166 | 0.623 | 0.165 | 0.485 | 0.246 | 0.308 | 0.129 | 0.173 | - | 2 s |

**Selection:** lstm beat the baseline reorder_point: pr_auc 0.3278 vs 0.1661 on the test period.

## Top recommendations on 2026-11-10

| Product | Warehouse | Risk | Priority | Reorder on | Quantity | Main reasons |
|---:|---:|---:|---|---|---:|---|
| 978 | 3 | 97% | high | 2026-11-10 | 63 | Low available stock; Long or unreliable supplier lead time; Seasonal peak ahead |
| 1475 | 1 | 96% | high | 2026-11-10 | 64 | Low available stock; Seasonal peak ahead; Long or unreliable supplier lead time |
| 1628 | 1 | 94% | high | 2026-11-10 | 34 | Low available stock; Seasonal peak ahead; Long or unreliable supplier lead time |
| 1909 | 1 | 93% | high | 2026-11-10 | 94 | Low available stock; Seasonal peak ahead; Long or unreliable supplier lead time |
| 1382 | 2 | 93% | high | 2026-11-10 | 8 | Low available stock; Long or unreliable supplier lead time; Seasonal peak ahead |
| 1928 | 1 | 91% | high | 2026-11-10 | 32 | Low available stock; Seasonal peak ahead; Long or unreliable supplier lead time |
| 951 | 1 | 90% | high | 2026-11-10 | 24 | Low available stock; Long or unreliable supplier lead time; Seasonal peak ahead |
| 888 | 3 | 89% | high | 2026-11-10 | 79 | Long or unreliable supplier lead time; Low available stock; Seasonal peak ahead |
| 330 | 2 | 89% | high | 2026-11-10 | 83 | Low available stock; Seasonal peak ahead; Long or unreliable supplier lead time |
| 1401 | 3 | 88% | high | 2026-11-10 | 29 | Long or unreliable supplier lead time; Low available stock; Demand rising recently |
| 281 | 1 | 88% | high | 2026-11-10 | 7 | Low available stock; Long or unreliable supplier lead time; Seasonal peak ahead |
| 181 | 1 | 88% | high | 2026-11-10 | 66 | Low available stock; Seasonal peak ahead; Long or unreliable supplier lead time |
| 1356 | 1 | 88% | high | 2026-11-10 | 57 | Low available stock; Seasonal peak ahead; Long or unreliable supplier lead time |
| 1583 | 1 | 87% | high | 2026-11-10 | 55 | Low available stock; Long or unreliable supplier lead time; Seasonal peak ahead |
| 459 | 1 | 86% | high | 2026-11-10 | 45 | Demand rising recently; Seasonal peak ahead; High or irregular demand |
