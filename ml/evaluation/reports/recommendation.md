# Product recommendation: model comparison

- Dataset: `orders499179-to2026-11-10-d109f294`, training run `20261118-0908`
- Split by order day: train 2024-11-11 to 2026-06-13 (580 days), validation to 2026-08-12 (60), test to 2026-11-10 (90)
- 400,000 training examples; 3,000 test queries: one product held out of each test-period basket with two or more products; every method ranks the whole catalogue for the rest of the basket, the customer and their earlier purchases.
- Metrics on the **test** queries at K=10: with one held-out product, Hit Rate@10 = Recall@10 (share of queries where it is in the top 10); `ndcg_at_10` (used for the selection) also rewards ranking it higher; `coverage`: share of the catalogue that appears in any top-10 list.

| Model | Type | ndcg_at_10 | hit_rate_at_10 | recall_at_10 | precision_at_10 | coverage | Epochs | Time |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **frequently_bought_together** (selected) | baseline | 0.403 | 0.559 | 0.559 | 0.056 | 0.897 | - | 1 s |
| two_tower | Keras | 0.357 | 0.462 | 0.462 | 0.046 | 0.779 | 15 | 117 s |
| gru_sequential | Keras | 0.298 | 0.400 | 0.400 | 0.040 | 0.732 | 16 | 816 s |
| deep_cross | Keras | 0.276 | 0.398 | 0.398 | 0.040 | 0.865 | 8 | 150 s |
| ncf | Keras | 0.249 | 0.370 | 0.370 | 0.037 | 0.839 | 6 | 145 s |

**Selection:** no model beat the baseline frequently_bought_together (ndcg_at_10 0.4034 on the test period).

## Example (first test query, selected method)

- In the basket: products 1967
- Top 10 recommended: 498, 1657, 987, 1689, 160, 1580, 316, 1526, 893, 1039
- Held-out product: 1580 (rank 6)
