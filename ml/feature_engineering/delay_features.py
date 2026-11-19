"""Order-delay features: will a shipment arrive after its expected delivery date?

The prediction is made at **dispatch**, when the parcel is handed to the carrier, using
only what is known at that moment:

- the order: units, lines, value, weight, parcels, priority, customer type;
- how it went so far: did it wait for stock, hours from confirmation to dispatch;
- the carrier: promised transit days and its late-delivery rate on parcels delivered
  *before* this dispatch day (no future outcomes);
- the warehouse: how full it was that day (share of storage volume in use);
- the calendar: peak season, month, weekday of dispatch;
- for the LSTM: the order's status events up to dispatch (status and hours since the
  order was placed). Events after dispatch (e.g. "delayed") are never used.

Label: delivered on a later day than expected (only delivered shipments are used).
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from feature_engineering.schema import FeatureSchema
from training.data import SCALE, read_frame

PRE_DISPATCH_STATUSES = (
    "created",
    "confirmed",
    "inventory_reserved",
    "partially_allocated",
    "backordered",
    "allocated",
    "picking",
    "picked",
    "packing",
    "packed",
    "shipped",
)
SEQUENCE_STEPS = 12
NUMERIC = (
    "log_units",
    "log_lines",
    "log_value",
    "log_weight_kg",
    "package_count",
    "waited_for_stock",
    "log_hours_to_dispatch",
    "transit_days",
    "carrier_late_rate",
    "warehouse_fill",
    "peak_season",
    "month_sin",
    "month_cos",
    "dispatch_weekday_sin",
    "dispatch_weekday_cos",
)
PRIORITIES = ("low", "normal", "high", "urgent")
SCHEMA = FeatureSchema("shipment_at_dispatch", dict.fromkeys(NUMERIC, "number"))


@dataclass
class DelaySet:
    numeric: pd.DataFrame  # SCHEMA columns
    categorical: np.ndarray  # carrier, warehouse, priority, customer type (one-hot)
    sequence: np.ndarray  # (n, SEQUENCE_STEPS, statuses + 1)
    wide: np.ndarray  # one-hot crosses: carrier x peak, waited x priority, fill band
    label: np.ndarray  # 1 = late
    shipped_day: np.ndarray  # datetime64[D]
    order_ids: np.ndarray
    category_names: list[str]  # names of the categorical columns

    def __len__(self) -> int:
        return len(self.label)

    def inputs(self) -> dict[str, np.ndarray]:
        return {
            "numeric": self.numeric.to_numpy("float32"),
            "categorical": self.categorical,
            "sequence": self.sequence,
            "wide": self.wide,
        }

    def subset(self, rows: np.ndarray) -> "DelaySet":
        return DelaySet(
            numeric=self.numeric.iloc[rows].reset_index(drop=True),
            categorical=self.categorical[rows],
            sequence=self.sequence[rows],
            wide=self.wide[rows],
            label=self.label[rows],
            shipped_day=self.shipped_day[rows],
            order_ids=self.order_ids[rows],
            category_names=self.category_names,
        )


def _carrier_late_rate(shipments: pd.DataFrame) -> np.ndarray:
    """Per shipment: the carrier's late share among parcels delivered before its dispatch
    day (prior 0.1 with weight 50 while the history is short)."""
    delivered = shipments.dropna(subset=["delivered_day"])
    daily = (
        delivered.groupby(["carrier_id", "delivered_day"])["late"]
        .agg(["sum", "count"])
        .reset_index()
    )
    rates = np.zeros(len(shipments))
    for carrier, part in daily.groupby("carrier_id"):
        part = part.sort_values("delivered_day")
        late_cum, count_cum = part["sum"].cumsum().to_numpy(), part["count"].cumsum().to_numpy()
        days = part["delivered_day"].to_numpy()
        mine = np.flatnonzero(shipments["carrier_id"].to_numpy() == carrier)
        # deliveries strictly before the dispatch day
        position = np.searchsorted(days, shipments["shipped_day"].to_numpy()[mine], side="left") - 1
        late = np.where(position >= 0, late_cum[np.maximum(position, 0)], 0)
        count = np.where(position >= 0, count_cum[np.maximum(position, 0)], 0)
        rates[mine] = (late + 0.1 * 50) / (count + 50)
    return rates


def _warehouse_fill(engine: Engine) -> pd.DataFrame:
    """Share of each warehouse's bin volume in use at the end of each day."""
    moves = read_frame(
        engine,
        "SELECT z.warehouse_id AS wh, date(m.created_at) AS day, "
        "SUM(m.on_hand_delta * p.length_cm * p.width_cm * p.height_cm) AS volume "
        "FROM inventory_movements m JOIN products p ON p.id = m.product_id "
        "JOIN bins b ON b.id = m.bin_id JOIN shelves s ON s.id = b.shelf_id "
        "JOIN racks r ON r.id = s.rack_id JOIN zones z ON z.id = r.zone_id GROUP BY 1, 2",
    )
    capacity = read_frame(
        engine,
        "SELECT z.warehouse_id AS wh, SUM(b.max_volume_cm3) AS capacity FROM bins b "
        "JOIN shelves s ON s.id = b.shelf_id JOIN racks r ON r.id = s.rack_id "
        "JOIN zones z ON z.id = r.zone_id GROUP BY 1",
    ).set_index("wh")["capacity"]
    moves = moves.sort_values(["wh", "day"])
    moves["used"] = moves.groupby("wh")["volume"].cumsum() / SCALE["length_cm"] ** 3
    moves["fill"] = moves["used"] / moves["wh"].map(capacity)
    return moves[["wh", "day", "fill"]]


def build_delay_set(
    engine: Engine, *, on_the_way: bool = False, as_of: date | None = None
) -> DelaySet:
    """Delivered shipments with their outcome (training), or with `on_the_way` the
    shipments not delivered yet (prediction; label NaN). The carrier history always uses
    the delivered ones.

    With `as_of` (a backtest), the data is seen as on that day: "delivered" means
    delivered on or before it, and "on the way" means dispatched by then but not
    delivered yet (their outcome is only known later)."""
    shipments = read_frame(
        engine,
        "SELECT s.order_id, s.carrier_id, c.code AS carrier, s.package_count, s.weight_kg, "
        "s.shipped_at, date(s.shipped_at) AS shipped_day, s.expected_delivery_date, "
        "date(s.delivered_at) AS delivered_day, o.warehouse_id AS wh, o.priority, "
        "o.subtotal, o.created_at, o.confirmed_at, cu.customer_type, "
        "(SELECT SUM(quantity) FROM order_items WHERE order_id = o.id) AS units, "
        "(SELECT COUNT(*) FROM order_items WHERE order_id = o.id) AS lines "
        "FROM shipments s JOIN orders o ON o.id = s.order_id JOIN carriers c "
        "ON c.id = s.carrier_id JOIN customers cu ON cu.id = o.customer_id "
        "ORDER BY s.shipped_at, s.order_id",
        dates=("shipped_at", "created_at", "confirmed_at"),
    )
    shipments["late"] = (shipments["delivered_day"] > shipments["expected_delivery_date"]).astype(
        int
    )
    history = read_frame(
        engine,
        "SELECT h.order_id, h.to_status, h.created_at FROM order_status_history h "
        "JOIN shipments s ON s.order_id = h.order_id "
        "WHERE h.created_at <= s.shipped_at ORDER BY h.order_id, h.created_at, h.id",
        dates=("created_at",),
    )
    history = history[history["to_status"].isin(PRE_DISPATCH_STATUSES)]
    waited = set(
        history.loc[history["to_status"].isin(("backordered", "partially_allocated")), "order_id"]
    )
    fill = _warehouse_fill(engine)
    shipments = shipments.merge(
        fill.rename(columns={"day": "shipped_day"}), on=["wh", "shipped_day"], how="left"
    )
    # Days without stock moves in a warehouse: the last known fill.
    shipments["fill"] = shipments.groupby("wh")["fill"].ffill().fillna(0)

    shipped = shipments["shipped_at"]
    months = shipped.dt.month.to_numpy()
    weekday = shipped.dt.weekday.to_numpy()
    transit = (
        pd.to_datetime(shipments["expected_delivery_date"])
        - pd.to_datetime(shipments["shipped_day"])
    ).dt.days
    hours = (shipped - shipments["confirmed_at"]).dt.total_seconds() / 3600
    numeric = pd.DataFrame(
        {
            "log_units": np.log1p(shipments["units"].astype(float)),
            "log_lines": np.log1p(shipments["lines"].astype(float)),
            "log_value": np.log1p(shipments["subtotal"].astype(float) / SCALE["money"]),
            "log_weight_kg": np.log1p(shipments["weight_kg"].astype(float) / SCALE["weight_kg"]),
            "package_count": shipments["package_count"].astype(float),
            "waited_for_stock": shipments["order_id"].isin(waited).astype(float),
            "log_hours_to_dispatch": np.log1p(hours.clip(lower=0).astype(float)),
            "transit_days": transit.astype(float),
            "carrier_late_rate": _carrier_late_rate(shipments),
            "warehouse_fill": shipments["fill"].astype(float),
            "peak_season": np.isin(months, (11, 12)).astype(float),
            "month_sin": np.sin(2 * np.pi * (months - 1) / 12),
            "month_cos": np.cos(2 * np.pi * (months - 1) / 12),
            "dispatch_weekday_sin": np.sin(2 * np.pi * weekday / 7),
            "dispatch_weekday_cos": np.cos(2 * np.pi * weekday / 7),
        }
    )
    SCHEMA.validate(numeric)

    one_hot = pd.get_dummies(
        shipments[["carrier", "wh", "priority", "customer_type"]].astype(str), dtype="float32"
    )
    categorical = one_hot.to_numpy("float32")

    # Status sequence up to dispatch, newest last, padded at the front.
    status_index = {s: i for i, s in enumerate(PRE_DISPATCH_STATUSES)}
    row_of = pd.Series(np.arange(len(shipments)), index=shipments["order_id"])
    created = shipments.set_index("order_id")["created_at"]
    history = history.assign(
        row=history["order_id"].map(row_of),
        status=history["to_status"].map(status_index),
        hours=(history["created_at"] - history["order_id"].map(created)).dt.total_seconds() / 3600,
    )
    history["step"] = history.groupby("order_id").cumcount(ascending=False)  # 0 = newest
    history = history[history["step"] < SEQUENCE_STEPS]
    sequence = np.zeros((len(shipments), SEQUENCE_STEPS, len(PRE_DISPATCH_STATUSES) + 1), "float32")
    position = SEQUENCE_STEPS - 1 - history["step"].to_numpy()
    rows = history["row"].to_numpy()
    sequence[rows, position, history["status"].to_numpy()] = 1
    sequence[rows, position, -1] = np.log1p(history["hours"].clip(lower=0).to_numpy())

    carriers = sorted(shipments["carrier"].unique())
    carrier = shipments["carrier"].map({c: i for i, c in enumerate(carriers)}).to_numpy()
    peak = numeric["peak_season"].to_numpy(int)
    waited_flag = numeric["waited_for_stock"].to_numpy(int)
    priority = shipments["priority"].map({p: i for i, p in enumerate(PRIORITIES)}).fillna(1)
    band = np.digitize(numeric["warehouse_fill"].to_numpy(), (0.5, 0.65, 0.8, 0.9))  # 0..4
    n = len(shipments)
    wide = np.zeros((n, len(carriers) * 2 + 2 * len(PRIORITIES) + 5), "float32")
    wide[np.arange(n), carrier * 2 + peak] = 1
    offset = len(carriers) * 2
    wide[np.arange(n), offset + waited_flag * len(PRIORITIES) + priority.to_numpy(int)] = 1
    wide[np.arange(n), offset + 2 * len(PRIORITIES) + band] = 1

    delivered = shipments["delivered_day"].notna().to_numpy().copy()
    dispatched = np.ones(len(shipments), bool)
    if as_of is not None:
        day = as_of.isoformat()
        delivered &= (shipments["delivered_day"].fillna("9999") <= day).to_numpy()
        dispatched = (shipments["shipped_day"] <= day).to_numpy()
    label = np.where(delivered, shipments["late"].to_numpy(), np.nan).astype("float32")
    full = DelaySet(
        numeric=numeric,
        categorical=categorical,
        sequence=sequence,
        wide=wide,
        label=label,
        shipped_day=pd.to_datetime(shipments["shipped_day"]).to_numpy("datetime64[D]"),
        order_ids=shipments["order_id"].to_numpy(),
        category_names=list(one_hot.columns),
    )
    return full.subset(np.flatnonzero(dispatched & ~delivered if on_the_way else delivered))
