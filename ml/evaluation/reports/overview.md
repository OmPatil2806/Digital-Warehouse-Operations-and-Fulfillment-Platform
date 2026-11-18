# Machine learning: overview of all use cases

Every use case compares simple baselines with several TensorFlow/Keras models on the most recent period (test), which no model saw while training. A network is selected only if it beats the best baseline (project document 12.4).

| Use case | Selected | Measured by | Selected | Best baseline | Best network | Gain over baseline |
|---|---|---|---:|---:|---:|---:|
| Demand forecasting | **lstm** | error of the 7/14/30-day demand totals (WAPE) | 0.351 | moving_average 0.412 | lstm 0.351 | +14.8% |
| Reorder recommendation | **lstm** | stockout warnings (PR-AUC) | 0.328 | reorder_point 0.166 | lstm 0.328 | +97.4% |
| Movement classification | **abc** (baseline) | clear, stable and useful groups (silhouette if usable) | 0.285 | abc 0.285 | autoencoder_kmeans not usable | baseline kept |
| Slotting | **dense_suitability** | picking time saved vs. the current layout (0 rule violations) | 0.498 | abc_slotting 0.497 | dense_suitability 0.498 | +0.3% |
| Order-delay prediction | **lstm_events** | late-delivery warnings (PR-AUC) | 0.119 | logistic_regression 0.116 | lstm_events 0.119 | +2.7% |
| Product recommendation | **frequently_bought_together** (baseline) | held-out product ranked in the top 10 (NDCG@10) | 0.403 | frequently_bought_together 0.403 | two_tower 0.357 | baseline kept |

Dataset: `orders499179-to2026-11-10-d109f294`.

## Demand forecasting

Training run `20261116-1416`; error of the 7/14/30-day demand totals (WAPE): `wape_totals`, lower is better. Details: [demand_forecasting.md](demand_forecasting.md).

| Model | Type | Test value | Status | Training time |
|---|---|---:|---|---:|
| lstm | Keras | 0.351 | selected | 187 s |
| gru | Keras | 0.352 | candidate | 157 s |
| transformer | Keras | 0.353 | candidate | 500 s |
| cnn_lstm | Keras | 0.355 | candidate | 110 s |
| moving_average | baseline | 0.412 | candidate | 0 s |
| seasonal_naive | baseline | 0.555 | candidate | 0 s |

## Reorder recommendation

Training run `20261116-1446`; stockout warnings (PR-AUC): `pr_auc`, higher is better. Details: [reorder.md](reorder.md).

| Model | Type | Test value | Status | Training time |
|---|---|---:|---|---:|
| lstm | Keras | 0.328 | selected | 349 s |
| wide_deep | Keras | 0.319 | candidate | 46 s |
| dense | Keras | 0.313 | candidate | 45 s |
| reorder_point | baseline | 0.166 | candidate | 2 s |

## Movement classification

Training run `20261116-1529`; clear, stable and useful groups (silhouette if usable): `selection_score`, higher is better. Details: [movement_classification.md](movement_classification.md).

| Model | Type | Test value | Status | Training time |
|---|---|---:|---|---:|
| abc | baseline | 0.285 | selected | 0 s |
| autoencoder_kmeans | Keras | not usable | candidate | 44 s |
| vae_kmeans | Keras | not usable | candidate | 24 s |
| dec | Keras | not usable | candidate | 46 s |

## Slotting

Training run `20261118-0807`; picking time saved vs. the current layout (0 rule violations): `selection_score`, higher is better. Details: [slotting.md](slotting.md).

| Model | Type | Test value | Status | Training time |
|---|---|---:|---|---:|
| dense_suitability | Keras | 0.498 | selected | 25 s |
| wide_deep_suitability | Keras | 0.498 | candidate | 31 s |
| abc_slotting | baseline | 0.497 | candidate | 4 s |

## Order-delay prediction

Training run `20261118-0836`; late-delivery warnings (PR-AUC): `pr_auc`, higher is better. Details: [delay_prediction.md](delay_prediction.md).

| Model | Type | Test value | Status | Training time |
|---|---|---:|---|---:|
| lstm_events | Keras | 0.119 | selected | 137 s |
| dense | Keras | 0.119 | candidate | 30 s |
| deep_cross | Keras | 0.119 | candidate | 33 s |
| wide_deep | Keras | 0.118 | candidate | 35 s |
| logistic_regression | baseline | 0.116 | candidate | 10 s |

## Product recommendation

Training run `20261118-0908`; held-out product ranked in the top 10 (NDCG@10): `ndcg_at_10`, higher is better. Details: [recommendation.md](recommendation.md).

| Model | Type | Test value | Status | Training time |
|---|---|---:|---|---:|
| frequently_bought_together | baseline | 0.403 | selected | 1 s |
| two_tower | Keras | 0.357 | candidate | 117 s |
| gru_sequential | Keras | 0.298 | candidate | 816 s |
| deep_cross | Keras | 0.276 | candidate | 150 s |
| ncf | Keras | 0.249 | candidate | 145 s |
