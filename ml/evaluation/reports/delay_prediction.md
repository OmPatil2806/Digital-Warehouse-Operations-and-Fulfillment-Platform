# Order-delay prediction: model comparison

- Dataset: `orders499179-to2026-11-10-d109f294`, training run `20261118-0836`
- Split by dispatch day: train 2024-11-11 to 2026-06-13 (580 days), validation to 2026-08-12 (60), test to 2026-11-10 (90)
- Delivered shipments: train 300,000 (9.7% late), validation 40,836 (8.0% late), test 61,718 (7.8% late)
- Metrics on the **test** period. `pr_auc` is used for the selection; precision, recall and F1 for late parcels at each model's threshold (best F1 on validation); `flagged_share`: share of shipments flagged as at risk; `brier` and `ece`: calibration (lower is better).

| Model | Type | pr_auc | roc_auc | precision | recall | f1 | flagged_share | brier | ece | Epochs | Time |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **lstm_events** (selected) | Keras | 0.119 | 0.573 | 0.106 | 0.357 | 0.164 | 0.263 | 0.072 | 0.011 | 18 | 137 s |
| dense | Keras | 0.119 | 0.575 | 0.107 | 0.344 | 0.163 | 0.252 | 0.072 | 0.013 | 17 | 30 s |
| deep_cross | Keras | 0.119 | 0.574 | 0.102 | 0.408 | 0.164 | 0.312 | 0.072 | 0.012 | 17 | 33 s |
| wide_deep | Keras | 0.118 | 0.573 | 0.104 | 0.389 | 0.164 | 0.294 | 0.072 | 0.010 | 20 | 35 s |
| logistic_regression | baseline | 0.116 | 0.570 | 0.102 | 0.401 | 0.163 | 0.308 | 0.072 | 0.006 | - | 10 s |

**Selection:** lstm_events beat the baseline logistic_regression: pr_auc 0.1189 vs 0.1157 on the test period.

## Riskiest shipments of the last test week (selected model)

| Order | Dispatched | Delay risk | Level | Main reasons | Actually late |
|---:|---|---:|---|---|---|
| 491153 | 2026-11-05 | 48% | medium | Waited for stock; Large order; Peak season | yes |
| 487788 | 2026-11-04 | 48% | medium | Waited for stock; Large order; Peak season | yes |
| 488924 | 2026-11-04 | 46% | medium | Waited for stock; Large order; Peak season | no |
| 486183 | 2026-11-04 | 45% | medium | Waited for stock; Large order; Peak season | no |
| 494481 | 2026-11-06 | 44% | medium | Waited for stock; Large order; Peak season | no |
| 488546 | 2026-11-06 | 43% | medium | Waited for stock; Large order; Peak season | no |
| 481703 | 2026-11-05 | 43% | medium | Waited for stock; Peak season; Large order | no |
| 493244 | 2026-11-05 | 43% | medium | Waited for stock; Peak season; Large order | no |
| 490804 | 2026-11-04 | 43% | medium | Waited for stock; Large order; Peak season | no |
| 481683 | 2026-11-06 | 43% | medium | Waited for stock; Peak season; Large order | no |
