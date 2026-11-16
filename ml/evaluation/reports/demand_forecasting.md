# Demand forecasting: model comparison

- Dataset: `orders499179-to2026-11-10-d109f294`, training run `20261116-1416`
- Split: train 2024-11-11 to 2026-06-13 (580 days), validation to 2026-08-12 (60), test to 2026-11-10 (90)
- Forecast windows: train 100,000, validation 10,000, test 18,000
- Metrics on the **test** period, per product: `wape_totals` (used for the selection) is the average WAPE of the 7-, 14- and 30-day demand totals; `wape`, `mae`, `rmse` are per day. Lower is better, except `coverage_80`: the share of days inside the forecast range (ideal 0.80)

| Model | Type | wape_totals | wape_7d_total | wape_14d_total | wape_30d_total | wape | mae | rmse | coverage_80 | Epochs | Time |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **lstm** (selected) | Keras | 0.351 | 0.460 | 0.342 | 0.252 | 0.949 | 1.524 | 3.928 | 0.861 | 20 | 187 s |
| gru | Keras | 0.352 | 0.460 | 0.343 | 0.254 | 0.943 | 1.516 | 3.926 | 0.854 | 18 | 157 s |
| transformer | Keras | 0.353 | 0.460 | 0.344 | 0.257 | 0.935 | 1.503 | 3.930 | 0.805 | 20 | 500 s |
| cnn_lstm | Keras | 0.355 | 0.462 | 0.346 | 0.258 | 0.939 | 1.509 | 3.937 | 0.881 | 15 | 110 s |
| moving_average | baseline | 0.412 | 0.507 | 0.403 | 0.327 | 0.990 | 1.591 | 4.036 | 0.883 | - | 0 s |
| seasonal_naive | baseline | 0.555 | 0.613 | 0.550 | 0.502 | 1.184 | 1.902 | 5.468 | 0.741 | - | 0 s |

**Selection:** lstm beat the baseline moving_average: wape_totals 0.3512 vs 0.4124 on the test period.
