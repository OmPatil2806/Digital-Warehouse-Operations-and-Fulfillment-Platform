"""Evaluation metrics for the six use cases (project document 12.3).

Plain functions on NumPy arrays, so baselines and Keras models are measured the same
way. Every function is tested on small examples whose answers are worked out by hand.

| Use case                | Metrics here                                                  |
|-------------------------|---------------------------------------------------------------|
| Demand forecasting      | mae, rmse, wape, mape_nonzero, interval_coverage              |
| Reorder / stockout      | classification_metrics (precision, recall, f1, roc_auc,      |
| Delay prediction        | pr_auc, brier), expected_calibration_error,                  |
|                         | calibration_table                                             |
| Movement classification | clustering_metrics (silhouette, davies_bouldin),              |
|                         | cluster_stability, rank_correlation                           |
| Slotting                | distance_reduction                                            |
| Recommendation          | precision_at_k, recall_at_k, hit_rate_at_k, ndcg_at_k,        |
|                         | catalogue_coverage, ranking_metrics                           |
"""

from collections.abc import Iterable, Sequence
from math import log2

import numpy as np
from numpy.typing import ArrayLike
from scipy.stats import rankdata
from sklearn.metrics import (
    adjusted_rand_score,
    average_precision_score,
    davies_bouldin_score,
    roc_auc_score,
    silhouette_score,
)


def _pair(y_true: ArrayLike, y_pred: ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    true = np.asarray(y_true, dtype=float).ravel()
    pred = np.asarray(y_pred, dtype=float).ravel()
    if true.shape != pred.shape:
        raise ValueError(f"y_true has {true.size} values, y_pred {pred.size}")
    if true.size == 0:
        raise ValueError("no values to evaluate")
    return true, pred


# ============================================================ forecasting (regression)
def mae(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Mean absolute error, in units."""
    true, pred = _pair(y_true, y_pred)
    return float(np.mean(np.abs(true - pred)))


def rmse(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Root mean squared error: punishes large misses more than MAE."""
    true, pred = _pair(y_true, y_pred)
    return float(np.sqrt(np.mean((true - pred) ** 2)))


def wape(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Weighted absolute percentage error: total absolute error / total actual demand.

    Works with the many zero-demand days (unlike MAPE). 0.25 means the forecast is off by
    25 % of the demand overall.
    """
    true, pred = _pair(y_true, y_pred)
    total = np.sum(np.abs(true))
    if total == 0:
        raise ValueError("WAPE is undefined when all actual values are zero")
    return float(np.sum(np.abs(true - pred)) / total)


def mape_nonzero(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Mean absolute percentage error over the days with demand (zero days left out)."""
    true, pred = _pair(y_true, y_pred)
    mask = true != 0
    if not mask.any():
        raise ValueError("MAPE needs at least one non-zero actual value")
    return float(np.mean(np.abs((true[mask] - pred[mask]) / true[mask])))


def interval_coverage(y_true: ArrayLike, lower: ArrayLike, upper: ArrayLike) -> float:
    """Share of actual values inside the forecast range [lower, upper]."""
    true, low = _pair(y_true, lower)
    _, high = _pair(y_true, upper)
    if np.any(low > high):
        raise ValueError("lower bound above upper bound")
    return float(np.mean((true >= low) & (true <= high)))


def regression_metrics(y_true: ArrayLike, y_pred: ArrayLike) -> dict[str, float]:
    result = {"mae": mae(y_true, y_pred), "rmse": rmse(y_true, y_pred)}
    if np.any(np.asarray(y_true) != 0):
        result["wape"] = wape(y_true, y_pred)
        result["mape_nonzero"] = mape_nonzero(y_true, y_pred)
    return result


# ====================================================== classification (stockout, delay)
def _binary(y_true: ArrayLike, y_score: ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    true, score = _pair(y_true, y_score)
    if not np.isin(true, (0, 1)).all():
        raise ValueError("y_true must contain only 0 and 1")
    if np.any((score < 0) | (score > 1)):
        raise ValueError("probabilities must be between 0 and 1")
    return true.astype(int), score


def precision_recall_f1(
    y_true: ArrayLike, y_score: ArrayLike, threshold: float = 0.5
) -> tuple[float, float, float]:
    """For the positive class (stockout, delayed) at a probability threshold.

    Precision: of the orders flagged, how many really were late. Recall: of the late
    orders, how many were flagged. F1: their harmonic mean. 0 when undefined.
    """
    true, score = _binary(y_true, y_score)
    flagged = score >= threshold
    hits = int(np.sum(flagged & (true == 1)))
    precision = hits / int(flagged.sum()) if flagged.any() else 0.0
    recall = hits / int(true.sum()) if true.any() else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def roc_auc(y_true: ArrayLike, y_score: ArrayLike) -> float:
    """Chance that a random positive is scored above a random negative (0.5 = guessing)."""
    true, score = _binary(y_true, y_score)
    if true.min() == true.max():
        raise ValueError("ROC-AUC needs both classes")
    return float(roc_auc_score(true, score))


def pr_auc(y_true: ArrayLike, y_score: ArrayLike) -> float:
    """Area under the precision-recall curve (average precision). Its 'guessing' level is
    the share of positives, so it shows rare events (delays, stockouts) better than ROC."""
    true, score = _binary(y_true, y_score)
    if not true.any():
        raise ValueError("PR-AUC needs at least one positive")
    return float(average_precision_score(true, score))


def brier(y_true: ArrayLike, y_score: ArrayLike) -> float:
    """Mean squared difference between probability and outcome (0 is perfect)."""
    true, score = _binary(y_true, y_score)
    return float(np.mean((score - true) ** 2))


def calibration_table(
    y_true: ArrayLike, y_score: ArrayLike, bins: int = 10
) -> list[tuple[float, float, int]]:
    """Per probability bin: (average predicted probability, observed rate, count).
    Well calibrated: "30 %" orders are late about 30 % of the time. Empty bins are left out."""
    true, score = _binary(y_true, y_score)
    edges = np.linspace(0, 1, bins + 1)
    index = np.clip(np.digitize(score, edges[1:-1], right=True), 0, bins - 1)
    table = []
    for b in range(bins):
        mask = index == b
        if mask.any():
            table.append((float(score[mask].mean()), float(true[mask].mean()), int(mask.sum())))
    return table


def expected_calibration_error(y_true: ArrayLike, y_score: ArrayLike, bins: int = 10) -> float:
    """Average gap between predicted probability and observed rate, weighted by bin size."""
    table = calibration_table(y_true, y_score, bins)
    total = sum(count for _, _, count in table)
    return float(sum(count * abs(p - o) for p, o, count in table) / total)


def classification_metrics(
    y_true: ArrayLike, y_score: ArrayLike, threshold: float = 0.5
) -> dict[str, float]:
    precision, recall, f1 = precision_recall_f1(y_true, y_score, threshold)
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "roc_auc": roc_auc(y_true, y_score),
        "pr_auc": pr_auc(y_true, y_score),
        "brier": brier(y_true, y_score),
        "ece": expected_calibration_error(y_true, y_score),
    }


def best_f1_threshold(y_true: ArrayLike, y_score: ArrayLike) -> float:
    """The probability threshold with the highest F1 (chosen on validation data only)."""
    _, score = _binary(y_true, y_score)
    candidates = np.unique(score)
    scores = [precision_recall_f1(y_true, y_score, t)[2] for t in candidates]
    return float(candidates[int(np.argmax(scores))])


# ================================================================== clustering (movement)
def clustering_metrics(features: ArrayLike, labels: ArrayLike) -> dict[str, float]:
    """Silhouette (-1..1, higher = clearer groups) and Davies-Bouldin (>= 0, lower = better)."""
    x = np.asarray(features, dtype=float)
    groups = np.asarray(labels)
    if len(np.unique(groups)) < 2:
        raise ValueError("clustering metrics need at least two clusters")
    return {
        "silhouette": float(silhouette_score(x, groups)),
        "davies_bouldin": float(davies_bouldin_score(x, groups)),
    }


def rank_correlation(a: ArrayLike, b: ArrayLike) -> float:
    """Spearman's rank correlation (-1..1): do higher values of `a` go with higher `b`?
    Ties get their average rank. 0 when one side is constant."""
    x, y = _pair(a, b)
    rank_x, rank_y = rankdata(x), rankdata(y)
    if rank_x.std() == 0 or rank_y.std() == 0:
        return 0.0
    return float(np.corrcoef(rank_x, rank_y)[0, 1])


def cluster_stability(runs: Sequence[ArrayLike]) -> float:
    """Average agreement (adjusted Rand index, 1 = identical grouping) between runs with
    different seeds; label numbers may differ between runs."""
    if len(runs) < 2:
        raise ValueError("stability needs at least two runs")
    scores = [
        adjusted_rand_score(np.asarray(a), np.asarray(b))
        for i, a in enumerate(runs)
        for b in runs[i + 1 :]
    ]
    return float(np.mean(scores))


# ======================================================================== slotting
def distance_reduction(
    before: ArrayLike, after: ArrayLike, weights: ArrayLike | None = None
) -> float:
    """Relative cut in (pick-weighted) walking distance: 0.2 means 20 % less walking."""
    old, new = _pair(before, after)
    w = np.ones_like(old) if weights is None else np.asarray(weights, dtype=float).ravel()
    total = float(np.sum(w * old))
    if total == 0:
        raise ValueError("no walking distance before")
    return float(1 - np.sum(w * new) / total)


# ================================================================== recommendation
def _top(recommended: Sequence[int], k: int) -> list[int]:
    if k < 1:
        raise ValueError("k must be at least 1")
    return list(recommended)[:k]


def precision_at_k(recommended: Sequence[int], relevant: Iterable[int], k: int) -> float:
    """Share of the top-k recommendations that are relevant."""
    wanted = set(relevant)
    return sum(item in wanted for item in _top(recommended, k)) / k


def recall_at_k(recommended: Sequence[int], relevant: Iterable[int], k: int) -> float:
    """Share of the relevant items found in the top k."""
    wanted = set(relevant)
    if not wanted:
        raise ValueError("recall needs at least one relevant item")
    return sum(item in wanted for item in _top(recommended, k)) / len(wanted)


def hit_rate_at_k(recommended: Sequence[int], relevant: Iterable[int], k: int) -> float:
    """1 if at least one relevant item is in the top k, else 0."""
    wanted = set(relevant)
    return float(any(item in wanted for item in _top(recommended, k)))


def ndcg_at_k(recommended: Sequence[int], relevant: Iterable[int], k: int) -> float:
    """Normalised discounted cumulative gain: relevant items count more near the top."""
    wanted = set(relevant)
    if not wanted:
        raise ValueError("NDCG needs at least one relevant item")
    gain = sum(
        1 / log2(rank + 2) for rank, item in enumerate(_top(recommended, k)) if item in wanted
    )
    ideal = sum(1 / log2(rank + 2) for rank in range(min(k, len(wanted))))
    return gain / ideal


def catalogue_coverage(
    recommendations: Iterable[Sequence[int]], catalogue_size: int, k: int
) -> float:
    """Share of the catalogue that appears in at least one top-k list."""
    if catalogue_size < 1:
        raise ValueError("catalogue_size must be at least 1")
    shown = {item for items in recommendations for item in _top(items, k)}
    return len(shown) / catalogue_size


def ranking_metrics(
    recommendations: Sequence[Sequence[int]],
    relevant: Sequence[Iterable[int]],
    catalogue_size: int,
    k: int = 10,
) -> dict[str, float]:
    """Averages over users (or baskets); lists with nothing relevant are skipped."""
    if len(recommendations) != len(relevant):
        raise ValueError("one relevant set per recommendation list is needed")
    pairs = [(recs, set(rel)) for recs, rel in zip(recommendations, relevant, strict=True) if rel]
    if not pairs:
        raise ValueError("no list has a relevant item")
    return {
        f"precision_at_{k}": float(np.mean([precision_at_k(r, w, k) for r, w in pairs])),
        f"recall_at_{k}": float(np.mean([recall_at_k(r, w, k) for r, w in pairs])),
        f"hit_rate_at_{k}": float(np.mean([hit_rate_at_k(r, w, k) for r, w in pairs])),
        f"ndcg_at_{k}": float(np.mean([ndcg_at_k(r, w, k) for r, w in pairs])),
        "coverage": catalogue_coverage(recommendations, catalogue_size, k),
    }
