"""Evaluation metrics, each on a small example worked out by hand."""

from math import log2, sqrt

import numpy as np
import pytest

from evaluation import metrics as m


# ------------------------------------------------------------------ forecasting
def test_regression_metrics_by_hand() -> None:
    actual, forecast = [10, 0, 5, 5], [8, 1, 5, 9]  # errors 2, 1, 0, 4
    assert m.mae(actual, forecast) == pytest.approx(7 / 4)
    assert m.rmse(actual, forecast) == pytest.approx(sqrt((4 + 1 + 0 + 16) / 4))
    assert m.wape(actual, forecast) == pytest.approx(7 / 20)
    # zero day left out: |2/10| + |0/5| + |4/5| over 3 days
    assert m.mape_nonzero(actual, forecast) == pytest.approx((0.2 + 0 + 0.8) / 3)
    assert m.regression_metrics(actual, forecast) == pytest.approx(
        {"mae": 1.75, "rmse": sqrt(21 / 4), "wape": 0.35, "mape_nonzero": 1 / 3}
    )


def test_perfect_forecast_and_all_zero_demand() -> None:
    assert m.mae([1, 2], [1, 2]) == 0 and m.wape([1, 2], [1, 2]) == 0
    assert m.regression_metrics([0, 0], [1, 0]) == {"mae": 0.5, "rmse": sqrt(0.5)}
    with pytest.raises(ValueError, match="all actual values are zero"):
        m.wape([0, 0], [1, 0])
    with pytest.raises(ValueError, match="non-zero"):
        m.mape_nonzero([0, 0], [1, 0])


def test_interval_coverage() -> None:
    assert m.interval_coverage([1, 5, 9, 4], [0, 6, 9, 0], [2, 8, 10, 3]) == 0.5
    with pytest.raises(ValueError, match="lower bound above"):
        m.interval_coverage([1], [3], [2])


@pytest.mark.parametrize("bad", [([1, 2], [1]), ([], [])])
def test_inputs_must_match(bad: tuple[list, list]) -> None:
    with pytest.raises(ValueError):
        m.mae(*bad)


# ---------------------------------------------------------------- classification
Y = [1, 1, 0, 0, 1, 0]
P = [0.9, 0.4, 0.6, 0.1, 0.8, 0.3]


def test_precision_recall_f1_by_hand() -> None:
    # flagged at 0.5: 0.9 (late), 0.6 (on time), 0.8 (late) -> 2 of 3 right; 2 of 3 late found
    precision, recall, f1 = m.precision_recall_f1(Y, P)
    assert (precision, recall) == pytest.approx((2 / 3, 2 / 3))
    assert f1 == pytest.approx(2 / 3)
    assert m.precision_recall_f1(Y, P, threshold=0.35) == pytest.approx((3 / 4, 1, 6 / 7))
    assert m.precision_recall_f1(Y, P, threshold=0.95) == (0.0, 0.0, 0.0)  # nothing flagged


def test_roc_and_pr_auc_by_hand() -> None:
    # 9 positive/negative pairs, positive ranked higher in 8 (0.4 < 0.6 is the miss)
    assert m.roc_auc(Y, P) == pytest.approx(8 / 9)
    # positives at ranks 1, 2, 4 -> precision 1, 1, 3/4 -> average 11/12
    assert m.pr_auc(Y, P) == pytest.approx(11 / 12)
    assert m.roc_auc([0, 1], [0.2, 0.9]) == 1.0 and m.roc_auc([1, 0], [0.2, 0.9]) == 0.0


def test_brier_and_calibration() -> None:
    assert m.brier([1, 0], [0.8, 0.4]) == pytest.approx((0.04 + 0.16) / 2)
    # perfectly calibrated: 25 % predicted, 1 in 4 happen
    assert m.expected_calibration_error([1, 0, 0, 0], [0.25] * 4) == pytest.approx(0)
    table = m.calibration_table([1, 0, 1, 1], [0.1, 0.15, 0.9, 0.95], bins=10)
    assert np.array(table) == pytest.approx(
        np.array([(0.1, 1.0, 1), (0.15, 0.0, 1), (0.9, 1.0, 1), (0.95, 1.0, 1)])
    )
    two = m.calibration_table([1, 0, 1, 1], [0.1, 0.15, 0.9, 0.95], bins=2)
    assert np.array(two) == pytest.approx(np.array([(0.125, 0.5, 2), (0.925, 1.0, 2)]))
    assert m.expected_calibration_error([1, 0, 1, 1], [0.1, 0.15, 0.9, 0.95], bins=2) == (
        pytest.approx((2 * 0.375 + 2 * 0.075) / 4)
    )


def test_classification_metrics_and_threshold() -> None:
    result = m.classification_metrics(Y, P)
    assert set(result) == {"precision", "recall", "f1", "roc_auc", "pr_auc", "brier", "ece"}
    assert result["roc_auc"] == pytest.approx(8 / 9)
    assert m.best_f1_threshold(Y, P) == pytest.approx(0.4)  # flags all three late orders


@pytest.mark.parametrize(
    ("y", "p", "message"),
    [([0, 2], [0.1, 0.2], "only 0 and 1"), ([0, 1], [0.1, 1.2], "between 0 and 1")],
)
def test_classification_input_checks(y: list, p: list, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        m.brier(y, p)


def test_auc_needs_both_classes() -> None:
    with pytest.raises(ValueError, match="both classes"):
        m.roc_auc([1, 1], [0.2, 0.3])
    with pytest.raises(ValueError, match="positive"):
        m.pr_auc([0, 0], [0.2, 0.3])


# --------------------------------------------------------------------- clustering
def test_clustering_metrics_separate_groups() -> None:
    points = np.array([[0, 0], [0, 1], [10, 0], [10, 1]])
    good = m.clustering_metrics(points, [0, 0, 1, 1])
    bad = m.clustering_metrics(points, [0, 1, 0, 1])
    assert good["silhouette"] > 0.8 > bad["silhouette"]
    assert good["davies_bouldin"] < bad["davies_bouldin"]
    # silhouette by hand for the first point: a = 1, b = (10 + sqrt(101)) / 2
    b = (10 + sqrt(101)) / 2
    assert good["silhouette"] == pytest.approx(1 - 1 / b)
    with pytest.raises(ValueError, match="two clusters"):
        m.clustering_metrics(points, [0, 0, 0, 0])


def test_cluster_stability_ignores_label_names() -> None:
    assert m.cluster_stability([[0, 0, 1, 1], [1, 1, 0, 0], [5, 5, 7, 7]]) == 1.0
    assert m.cluster_stability([[0, 0, 1, 1], [0, 1, 0, 1]]) < 0.5
    with pytest.raises(ValueError, match="two runs"):
        m.cluster_stability([[0, 1]])


def test_rank_correlation_by_hand() -> None:
    assert m.rank_correlation([1, 2, 3], [10, 20, 35]) == pytest.approx(1.0)
    assert m.rank_correlation([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    # ranks (1, 2, 3, 4) vs (2, 1, 4, 3): 1 - 6 * (1+1+1+1) / (4 * 15) = 0.6
    assert m.rank_correlation([1, 2, 3, 4], [5, 1, 9, 7]) == pytest.approx(0.6)
    assert m.rank_correlation([0, 0, 1], [1, 2, 3]) > 0  # ties share ranks
    assert m.rank_correlation([1, 1, 1], [1, 2, 3]) == 0.0


# ----------------------------------------------------------------------- slotting
def test_distance_reduction() -> None:
    assert m.distance_reduction([10, 20], [5, 20]) == pytest.approx(5 / 30)
    # weighted by picks: the frequently picked product matters most
    assert m.distance_reduction([10, 20], [5, 20], weights=[9, 1]) == pytest.approx(45 / 110)
    assert m.distance_reduction([10], [12]) == pytest.approx(-0.2)  # worse: negative


# ------------------------------------------------------------------ recommendation
def test_ranking_metrics_by_hand() -> None:
    recommended, relevant = [7, 3, 9, 1], {3, 1, 5}
    assert m.precision_at_k(recommended, relevant, 2) == 0.5
    assert m.recall_at_k(recommended, relevant, 4) == pytest.approx(2 / 3)
    assert m.hit_rate_at_k(recommended, relevant, 1) == 0.0
    assert m.hit_rate_at_k(recommended, relevant, 2) == 1.0
    gain = 1 / log2(3) + 1 / log2(5)  # hits at ranks 2 and 4
    ideal = 1 / log2(2) + 1 / log2(3) + 1 / log2(4)
    assert m.ndcg_at_k(recommended, relevant, 4) == pytest.approx(gain / ideal)
    assert m.ndcg_at_k([3, 1, 5], relevant, 3) == pytest.approx(1.0)
    # more relevant items than k: two hits in two places is still perfect
    assert m.ndcg_at_k([3, 1], relevant, 2) == pytest.approx(1.0)


def test_coverage_and_averages() -> None:
    lists = [[1, 2, 3], [1, 2, 4], [9, 9, 9]]
    assert m.catalogue_coverage(lists, catalogue_size=10, k=2) == pytest.approx(3 / 10)
    result = m.ranking_metrics(lists, [{2}, {4}, set()], catalogue_size=10, k=2)
    # third list has nothing relevant: skipped in the averages
    assert result["hit_rate_at_2"] == 0.5 and result["precision_at_2"] == 0.25
    assert result["coverage"] == pytest.approx(0.3)
    with pytest.raises(ValueError, match="k must"):
        m.precision_at_k([1], {1}, 0)
