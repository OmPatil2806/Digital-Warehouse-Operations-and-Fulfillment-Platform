"""Demand forecasting features: daily units per product and forecast windows.

Demand is what customers *ordered* each day (order lines by order date), including
orders cancelled later: the wish to buy happened. Every product has a value for every
day (0 when nothing was ordered), so 2,000 products x 730 days on the full dataset.

A forecast is made at an *origin* day: the model sees the `window` days before it and
predicts the `horizon` days from the origin on. Nothing on or after the origin is used
as input, so no future information leaks in::

    |------ window (history) ------| origin |----- horizon (targets) -----|

Inputs per window day: demand (scaled per product), promotion flag, weekday and season
(as sine/cosine). Known in advance for the forecast days: their weekday and season.
Per product: its category and its typical demand level.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from feature_engineering.schema import FeatureSchema
from training.data import read_frame

DEMAND_SCHEMA = FeatureSchema(
    "daily_demand",
    {
        "product_id": "integer",
        "day": "timestamp",
        "units": "number",
        "promo": "flag",
    },
)
HISTORY_FEATURES = ("units", "promo", "weekday_sin", "weekday_cos", "season_sin", "season_cos")
FUTURE_FEATURES = ("weekday_sin", "weekday_cos", "season_sin", "season_cos")
MIN_SCALE = 0.1  # units per day: slow products are not blown up by a tiny divisor


@dataclass
class DemandData:
    """Daily demand as a dense matrix: units[p, d] for product index p and day index d."""

    product_ids: np.ndarray  # (products,)
    categories: np.ndarray  # (products,) category index 0..n-1
    category_names: list[str]
    first: date
    units: np.ndarray  # (products, days) float32
    promo: np.ndarray  # (products, days) float32, 1 when the product sold discounted

    @property
    def days(self) -> int:
        return self.units.shape[1]

    def day_index(self, day: date) -> int:
        index = (day - self.first).days
        if not 0 <= index < self.days:
            raise ValueError(f"{day} is outside the demand history")
        return index

    def day(self, index: int) -> date:
        return self.first + timedelta(days=index)


def load_daily_demand(engine: Engine) -> pd.DataFrame:
    """One row per product and day with orders: units and whether any line was discounted."""
    frame = read_frame(
        engine,
        "SELECT oi.product_id, date(o.created_at) AS day, SUM(oi.quantity) AS units, "
        "MAX(oi.unit_price < p.unit_price) AS promo FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id "
        "GROUP BY oi.product_id, date(o.created_at)",
    )
    frame["day"] = pd.to_datetime(frame["day"])
    frame["units"] = frame["units"].astype(float)
    frame["promo"] = frame["promo"].astype(int)
    return DEMAND_SCHEMA.validate(frame)


def build_demand_data(engine: Engine, first: date, last: date) -> DemandData:
    """The full product x day matrix from `first` to `last` (missing days are 0)."""
    products = read_frame(
        engine,
        "SELECT p.id, c.name AS category FROM products p JOIN categories c "
        "ON c.id = p.category_id ORDER BY p.id",
    )
    names = sorted(products["category"].unique())
    category_index = {name: i for i, name in enumerate(names)}
    days = (last - first).days + 1
    row_of = {pid: i for i, pid in enumerate(products["id"])}
    units = np.zeros((len(products), days), dtype="float32")
    promo = np.zeros((len(products), days), dtype="float32")
    daily = load_daily_demand(engine)
    offsets = (daily["day"] - pd.Timestamp(first)).dt.days.to_numpy()
    inside = (offsets >= 0) & (offsets < days)
    rows = daily["product_id"].map(row_of).to_numpy()[inside]
    units[rows, offsets[inside]] = daily["units"].to_numpy()[inside]
    promo[rows, offsets[inside]] = daily["promo"].to_numpy()[inside]
    return DemandData(
        product_ids=products["id"].to_numpy(),
        categories=products["category"].map(category_index).to_numpy(),
        category_names=names,
        first=first,
        units=units,
        promo=promo,
    )


def calendar(first: date, days: int) -> np.ndarray:
    """(days, 4): weekday and day-of-year as sine/cosine (Monday and Sunday are close)."""
    stamps = pd.date_range(first, periods=days, freq="D")
    weekday = 2 * np.pi * stamps.weekday.to_numpy() / 7
    season = 2 * np.pi * (stamps.dayofyear.to_numpy() - 1) / 365.25
    return np.stack(
        [np.sin(weekday), np.cos(weekday), np.sin(season), np.cos(season)], axis=1
    ).astype("float32")


def product_scale(data: DemandData, until: int) -> np.ndarray:
    """Typical daily demand per product, from the days before index `until` only."""
    if until < 1:
        raise ValueError("at least one day of history is needed for the scale")
    return np.maximum(data.units[:, :until].mean(axis=1), MIN_SCALE).astype("float32")


@dataclass
class Windows:
    """Model inputs and targets for many (product, origin) pairs."""

    history: np.ndarray  # (n, window, 6) scaled demand, promo, calendar
    future: np.ndarray  # (n, horizon, 4) calendar of the forecast days
    static: np.ndarray  # (n, categories + 1) category one-hot, log of the scale
    target: np.ndarray  # (n, horizon) units, NOT scaled
    scale: np.ndarray  # (n,) divide units by this for the model, multiply predictions back
    products: np.ndarray  # (n,) product index
    origins: np.ndarray  # (n,) day index of the first forecast day

    def __len__(self) -> int:
        return len(self.target)

    def inputs(self) -> dict[str, np.ndarray]:
        return {"history": self.history, "future": self.future, "static": self.static}

    def subset(self, rows: np.ndarray) -> "Windows":
        return Windows(*(getattr(self, f)[rows] for f in self.__dataclass_fields__))

    def raw_history(self) -> np.ndarray:
        """The window's demand in units (for the baselines)."""
        return self.history[:, :, 0] * self.scale[:, None]


def origins_between(first: int, last: int, *, window: int, horizon: int, stride: int) -> list[int]:
    """Origins whose window starts on/after `first` and whose horizon ends on/before `last`
    (day indices, inclusive), every `stride` days counted back from the latest one."""
    latest = last - horizon + 1
    earliest = max(first + window, 0)
    if latest < earliest:
        return []
    return list(range(latest, earliest - 1, -stride))[::-1]


def make_windows(
    data: DemandData,
    origins: list[int],
    *,
    window: int,
    horizon: int,
    scale: np.ndarray,
    products: np.ndarray | None = None,
) -> Windows:
    """Windows for every product (or `products`) at every origin."""
    product_rows = np.arange(len(data.product_ids)) if products is None else np.asarray(products)
    if not origins:
        raise ValueError("no forecast origins: the period is shorter than window + horizon")
    cal = calendar(data.first, data.days)
    categories = len(data.category_names)
    pairs = [(p, o) for o in origins for p in product_rows]
    p_idx = np.array([p for p, _ in pairs])
    o_idx = np.array([o for _, o in pairs])
    if (o_idx - window).min() < 0 or (o_idx + horizon).max() > data.days:
        raise ValueError("a window or horizon falls outside the demand history")
    past = o_idx[:, None] + np.arange(-window, 0)[None, :]  # (n, window)
    ahead = o_idx[:, None] + np.arange(horizon)[None, :]  # (n, horizon)
    s = scale[p_idx]
    history = np.concatenate(
        [
            (data.units[p_idx[:, None], past] / s[:, None])[..., None],
            data.promo[p_idx[:, None], past][..., None],
            cal[past],
        ],
        axis=2,
    ).astype("float32")
    static = np.zeros((len(pairs), categories + 1), dtype="float32")
    static[np.arange(len(pairs)), data.categories[p_idx]] = 1
    static[:, -1] = np.log1p(s)
    return Windows(
        history=history,
        future=cal[ahead],
        static=static,
        target=data.units[p_idx[:, None], ahead].astype("float32"),
        scale=s.astype("float32"),
        products=p_idx,
        origins=o_idx,
    )


def latest_windows(data: DemandData, *, window: int, horizon: int, scale: np.ndarray) -> Windows:
    """Inference: every product's last `window` days, forecasting the `horizon` days after
    the end of the history (their demand is unknown, so the targets are zeros)."""
    origin = data.days
    if origin - window < 0:
        raise ValueError("not enough history for the window")
    cal = calendar(data.first, data.days + horizon)
    products = np.arange(len(data.product_ids))
    past = origin + np.arange(-window, 0)
    history = np.concatenate(
        [
            (data.units[:, past] / scale[:, None])[..., None],
            data.promo[:, past][..., None],
            np.broadcast_to(cal[past], (len(products), window, cal.shape[1])),
        ],
        axis=2,
    ).astype("float32")
    static = np.zeros((len(products), len(data.category_names) + 1), dtype="float32")
    static[products, data.categories] = 1
    static[:, -1] = np.log1p(scale)
    return Windows(
        history=history,
        future=np.broadcast_to(cal[origin : origin + horizon], (len(products), horizon, 4)).copy(),
        static=static,
        target=np.zeros((len(products), horizon), "float32"),
        scale=scale.astype("float32"),
        products=products,
        origins=np.full(len(products), origin),
    )
