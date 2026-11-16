"""Reorder recommendation features: will a product run out in a warehouse soon?

For every product and warehouse the stock history is rebuilt day by day from the
inventory movements (available = on hand - reserved - damaged at the end of each day),
together with the daily demand and the units still on order from suppliers.

A *snapshot* looks at one product in one warehouse on one day, using only what was known
that evening, and asks: does its available stock reach zero during the next `horizon`
days? Snapshots where it is already out of stock are left out: those need no forecast.

Features per snapshot (all from the past):
- stock: available units, available + on order, days of cover for both
- demand: average units per day over the last 7, 28 and 56 days, spread, trend
- season: last year's demand in the coming weeks compared with last year's average
- time of year, supplier promised lead time and reliability, category, warehouse
- for the LSTM: the last `sequence_days` of demand and available stock
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from feature_engineering.schema import FeatureSchema
from training.data import read_frame

COVER_BUCKETS = (7, 14, 21, 35, 56)  # days of cover: <7, 7-14, ..., >= 56
NUMERIC = (
    "log_available",
    "log_position",
    "log_on_order",
    "log_demand_7",
    "log_demand_28",
    "log_demand_56",
    "log_demand_std_28",
    "trend_7_28",
    "log_cover_days",
    "log_position_cover_days",
    "season_ratio",
    "has_last_year",
    "month_sin",
    "month_cos",
    "peak_season",
    "lead_days",
    "supplier_reliability",
)
SCHEMA = FeatureSchema("reorder_snapshot", dict.fromkeys(NUMERIC, "number"))


@dataclass
class StockHistory:
    """Daily matrices per series (one series = one product in one warehouse)."""

    first: date
    product_ids: np.ndarray  # (series,)
    warehouse_ids: np.ndarray  # (series,)
    available: np.ndarray  # (series, days) end of day
    on_order: np.ndarray  # (series, days) end of day
    demand: np.ndarray  # (series, days) units ordered that day
    categories: np.ndarray  # (series,) category index
    category_names: list[str]
    warehouse_count: int
    lead_days: np.ndarray  # (series,) promised lead time of the preferred supplier
    reliability: np.ndarray  # (series,) the supplier's stored reliability score (0-1)

    @property
    def days(self) -> int:
        return self.available.shape[1]

    def day(self, index: int) -> date:
        return self.first + timedelta(days=index)


def _grid(
    frame: pd.DataFrame,
    value: str,
    series: pd.MultiIndex,
    first: date,
    days: int,
    *,
    late_to_last_day: bool = False,
):
    """(series, days) matrix of a per-day value (missing days 0). With `late_to_last_day`,
    values after the last day count on the last day (stock moves just after midnight)."""
    offsets = (pd.to_datetime(frame["day"]) - pd.Timestamp(first)).dt.days.to_numpy()
    if late_to_last_day:
        offsets = np.minimum(offsets, days - 1)
    rows = series.get_indexer(pd.MultiIndex.from_arrays([frame["product_id"], frame["wh"]]))
    keep = (rows >= 0) & (offsets >= 0) & (offsets < days)
    grid = np.zeros((len(series), days), dtype="float32")
    np.add.at(grid, (rows[keep], offsets[keep]), frame[value].to_numpy(dtype="float32")[keep])
    return grid


def build_stock_history(engine: Engine, first: date, last: date) -> StockHistory:
    days = (last - first).days + 1
    bins = read_frame(
        engine,
        "SELECT b.id AS bin_id, z.warehouse_id AS wh FROM bins b JOIN shelves s "
        "ON s.id = b.shelf_id JOIN racks r ON r.id = s.rack_id JOIN zones z ON z.id = r.zone_id",
    )
    moves = read_frame(
        engine,
        "SELECT product_id, bin_id, date(created_at) AS day, movement_type, reason, "
        "on_hand_delta - reserved_delta - damaged_delta AS change, on_hand_delta "
        "FROM inventory_movements",
    ).merge(bins, on="bin_id")
    products = read_frame(
        engine,
        "SELECT p.id AS product_id, c.name AS category, COALESCE(s.lead_time_days, 14) AS lead, "
        "COALESCE(s.reliability_score, 80) AS reliability FROM products p "
        "JOIN categories c ON c.id = p.category_id "
        "LEFT JOIN suppliers s ON s.id = p.default_supplier_id ORDER BY p.id",
    )
    warehouses = read_frame(engine, "SELECT id FROM warehouses ORDER BY id")["id"].to_numpy()
    series = pd.MultiIndex.from_product([products["product_id"], warehouses])
    product_ids = series.get_level_values(0).to_numpy()
    warehouse_ids = series.get_level_values(1).to_numpy()

    available = np.cumsum(
        _grid(moves, "change", series, first, days, late_to_last_day=True), axis=1
    )
    # Opening stock comes in on the first morning; later receipts are purchase deliveries.
    receipts = moves[(moves.movement_type == "receipt") & (moves.reason != "Opening stock")]
    ordered = read_frame(
        engine,
        "SELECT i.product_id, po.warehouse_id AS wh, date(po.ordered_at) AS day, "
        "i.quantity AS units FROM purchase_order_items i "
        "JOIN purchase_orders po ON po.id = i.purchase_order_id WHERE po.ordered_at IS NOT NULL",
    )
    on_order = np.cumsum(
        _grid(ordered, "units", series, first, days)
        - _grid(receipts, "on_hand_delta", series, first, days),
        axis=1,
    )
    sales = read_frame(
        engine,
        "SELECT oi.product_id, o.warehouse_id AS wh, date(o.created_at) AS day, "
        "oi.quantity AS units FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "WHERE o.warehouse_id IS NOT NULL",
    )
    names = sorted(products["category"].unique())
    info = products.set_index("product_id").loc[product_ids]
    reliability = info["reliability"].to_numpy(dtype="float32")
    return StockHistory(
        first=first,
        product_ids=product_ids,
        warehouse_ids=warehouse_ids,
        available=np.maximum(available, 0),
        on_order=np.maximum(on_order, 0),
        demand=_grid(sales, "units", series, first, days),
        categories=info["category"].map({n: i for i, n in enumerate(names)}).to_numpy(),
        category_names=names,
        warehouse_count=len(warehouses),
        lead_days=info["lead"].to_numpy(dtype="float32"),
        reliability=reliability / 100 if reliability.max() > 1 else reliability,
    )


@dataclass
class Snapshots:
    numeric: pd.DataFrame  # SCHEMA columns
    categorical: np.ndarray  # (n, categories + warehouses) one-hot
    wide: np.ndarray  # (n, ...) one-hot crosses for the wide part
    sequence: np.ndarray  # (n, sequence_days, 2) log demand, log available
    label: np.ndarray  # (n,) 1 = runs out within the horizon
    series: np.ndarray  # (n,) series index
    day: np.ndarray  # (n,) day index of the snapshot
    demand_28: np.ndarray  # (n,) units per day (for the baseline and recommendations)
    position: np.ndarray  # (n,) available + on order
    available: np.ndarray  # (n,)

    def __len__(self) -> int:
        return len(self.label)

    def inputs(self) -> dict[str, np.ndarray]:
        return {
            "numeric": self.numeric.to_numpy("float32"),
            "categorical": self.categorical,
            "wide": self.wide,
            "sequence": self.sequence,
        }

    def subset(self, rows: np.ndarray) -> "Snapshots":
        values = {f: getattr(self, f) for f in self.__dataclass_fields__}
        values["numeric"] = self.numeric.iloc[rows].reset_index(drop=True)
        return Snapshots(
            **{k: v if k == "numeric" else v[rows] for k, v in values.items()}  # type: ignore[arg-type]
        )


def snapshot_days(first: int, last: int, *, horizon: int, stride: int, warmup: int) -> list[int]:
    """Snapshot days whose look-ahead (day+1 .. day+horizon) ends on/before `last`."""
    latest, earliest = last - horizon, max(first, warmup)
    return list(range(latest, earliest - 1, -stride))[::-1] if latest >= earliest else []


def make_snapshots(
    history: StockHistory,
    days: list[int],
    *,
    horizon: int,
    sequence_days: int = 28,
    include_out_of_stock: bool = False,
) -> Snapshots:
    """Snapshots of every series on `days`. Labels are NaN where the look-ahead runs past
    the end of the history (used for today's recommendations)."""
    if not days:
        raise ValueError("no snapshot days: the period is too short")
    if min(days) < max(56, sequence_days) - 1:
        raise ValueError("snapshots need 56 days of history before them")
    n_series = len(history.product_ids)
    s_idx = np.tile(np.arange(n_series), len(days))
    d_idx = np.repeat(np.asarray(days), n_series)
    available = history.available[s_idx, d_idx]
    keep = np.ones(len(s_idx), bool) if include_out_of_stock else available > 0
    s_idx, d_idx, available = s_idx[keep], d_idx[keep], available[keep]

    cum = np.concatenate([np.zeros((n_series, 1), "float32"), np.cumsum(history.demand, 1)], 1)

    def mean_demand(window: int, end_offset: int = 1) -> np.ndarray:  # days up to the snapshot
        end = d_idx + end_offset
        start = np.maximum(end - window, 0)
        return (cum[s_idx, end] - cum[s_idx, start]) / (end - start)

    d7, d28, d56 = mean_demand(7), mean_demand(28), mean_demand(56)
    past = d_idx[:, None] + np.arange(-27, 1)[None, :]
    std28 = history.demand[s_idx[:, None], past].std(axis=1)
    on_order = history.on_order[s_idx, d_idx]
    position = available + on_order
    rate = np.maximum(d28, 0.05)
    # Last year: demand in the coming weeks vs the 8 weeks before (seasonal pattern).
    year_ago = d_idx - 365
    has_year = year_ago - 56 >= 0
    safe = np.where(has_year, year_ago, 56)
    ahead_last_year = (
        cum[s_idx, np.minimum(safe + 1 + horizon, history.days)] - cum[s_idx, safe + 1]
    ) / horizon
    before_last_year = (cum[s_idx, safe + 1] - cum[s_idx, safe + 1 - 56]) / 56
    season = np.where(has_year, (ahead_last_year + 0.1) / (before_last_year + 0.1), 1.0)
    months = np.array([history.day(int(d)).month for d in d_idx])
    numeric = pd.DataFrame(
        {
            "log_available": np.log1p(available),
            "log_position": np.log1p(position),
            "log_on_order": np.log1p(on_order),
            "log_demand_7": np.log1p(d7),
            "log_demand_28": np.log1p(d28),
            "log_demand_56": np.log1p(d56),
            "log_demand_std_28": np.log1p(std28),
            "trend_7_28": np.clip((d7 + 0.1) / (d28 + 0.1), 0, 5),
            "log_cover_days": np.log1p(np.minimum(available / rate, 365)),
            "log_position_cover_days": np.log1p(np.minimum(position / rate, 365)),
            "season_ratio": np.clip(season, 0, 5),
            "has_last_year": has_year.astype(float),
            "month_sin": np.sin(2 * np.pi * (months - 1) / 12),
            "month_cos": np.cos(2 * np.pi * (months - 1) / 12),
            "peak_season": np.isin(months, (11, 12)).astype(float),
            "lead_days": history.lead_days[s_idx].astype(float),
            "supplier_reliability": history.reliability[s_idx].astype(float),
        }
    ).astype("float64")
    SCHEMA.validate(numeric)

    n = len(s_idx)
    cats, whs = len(history.category_names), history.warehouse_count
    categorical = np.zeros((n, cats + whs), "float32")
    categorical[np.arange(n), history.categories[s_idx]] = 1
    wh_index = np.searchsorted(np.unique(history.warehouse_ids), history.warehouse_ids[s_idx])
    categorical[np.arange(n), cats + wh_index] = 1
    cover = np.digitize(available / rate, COVER_BUCKETS)  # 0..len(buckets)
    peak = numeric["peak_season"].to_numpy(int)
    wide = np.zeros((n, (len(COVER_BUCKETS) + 1) * 2 + 12), "float32")
    wide[np.arange(n), cover * 2 + peak] = 1  # cover bucket x peak season
    wide[np.arange(n), (len(COVER_BUCKETS) + 1) * 2 + months - 1] = 1  # month

    seq_days = d_idx[:, None] + np.arange(-sequence_days + 1, 1)[None, :]
    sequence = np.stack(
        [
            np.log1p(history.demand[s_idx[:, None], seq_days]),
            np.log1p(history.available[s_idx[:, None], seq_days]),
        ],
        axis=2,
    ).astype("float32")

    ahead = np.minimum(d_idx[:, None] + np.arange(1, horizon + 1)[None, :], history.days - 1)
    label = (history.available[s_idx[:, None], ahead] <= 0).any(axis=1).astype("float32")
    label[d_idx + horizon >= history.days] = np.nan  # the future is unknown: prediction only
    return Snapshots(
        numeric=numeric,
        categorical=categorical,
        wide=wide,
        sequence=sequence,
        label=label,
        series=s_idx,
        day=d_idx,
        demand_28=d28.astype("float32"),
        position=position.astype("float32"),
        available=available.astype("float32"),
    )
