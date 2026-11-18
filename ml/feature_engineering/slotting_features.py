"""Slotting features: products, bins, how often each product is picked, where it sits now,
and the estimated pick time of a product in a bin.

**Storage type** is not stored per product, so it is derived from where its deliveries
were put away: mostly into cold bins -> cold, hazardous bins -> hazardous, otherwise
general (picking or bulk bins). These are hard rules for every slotting method.

**Pick face**: each product gets one home bin per warehouse, sized for a week of its
recent units (at least one unit, at most what fits in the largest bin it may use). A
bin may hold several products' pick faces as long as their weight and volume fit.

**Estimated pick time** (seconds per pick), as in the simulation's picking model plus a
handling allowance for awkward shelves:

    2 x distance / walking speed + 15 s + 4 s per unit
    + 0.5 s per kg for each shelf level above 2 (heavy goods up high are slow and unsafe)
    + 3 s from level 4 (step ladder)
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from training.data import SCALE, read_frame

WALK_SPEED_M_PER_S = 1.2  # as data_generation.generate_fulfillment
SECONDS_PER_PICK, SECONDS_PER_UNIT = 15.0, 4.0
SECONDS_PER_KG_PER_LEVEL, LADDER_LEVEL, LADDER_SECONDS = 0.5, 4, 3.0
HEAVY_KG = 8.0
FACE_DAYS = 7  # a pick face holds about a week of picks
STORAGE_TYPES = ("general", "cold", "hazardous")
ZONE_TYPES = ("picking", "bulk", "cold", "hazardous")
ALLOWED_ZONES = {"general": ("picking", "bulk"), "cold": ("cold",), "hazardous": ("hazardous",)}


@dataclass
class Layout:
    """Products and bins (one row each) of the whole dataset."""

    product_ids: np.ndarray
    weight_kg: np.ndarray
    volume_cm3: np.ndarray
    category: np.ndarray  # index into category_names
    category_names: list[str]
    storage: np.ndarray  # index into STORAGE_TYPES
    bin_ids: np.ndarray
    bin_warehouse: np.ndarray
    bin_zone: np.ndarray  # index into ZONE_TYPES, -1 = returns (never slotted)
    bin_level: np.ndarray
    bin_distance: np.ndarray  # metres to the packing station
    bin_max_kg: np.ndarray
    bin_max_cm3: np.ndarray
    warehouse_ids: np.ndarray

    def allowed(self, product: int) -> np.ndarray:
        """Boolean mask of the bins this product may go into (zone rule only)."""
        zones = [ZONE_TYPES.index(z) for z in ALLOWED_ZONES[STORAGE_TYPES[self.storage[product]]]]
        return np.isin(self.bin_zone, zones)


def load_layout(engine: Engine) -> Layout:
    products = read_frame(
        engine,
        "SELECT p.id, p.weight_kg, p.length_cm * p.width_cm * p.height_cm AS volume, "
        "c.name AS category FROM products p JOIN categories c ON c.id = p.category_id "
        "ORDER BY p.id",
    )
    bins = read_frame(
        engine,
        "SELECT b.id, z.warehouse_id, z.zone_type, s.level, r.distance_to_packing_m AS distance, "
        "b.max_weight_kg, b.max_volume_cm3 FROM bins b JOIN shelves s ON s.id = b.shelf_id "
        "JOIN racks r ON r.id = s.rack_id JOIN zones z ON z.id = r.zone_id "
        "WHERE b.is_active = 1 ORDER BY b.id",
    )
    put_away = read_frame(
        engine,
        "SELECT m.product_id, z.zone_type, SUM(m.on_hand_delta) AS units "
        "FROM inventory_movements m JOIN bins b ON b.id = m.bin_id "
        "JOIN shelves s ON s.id = b.shelf_id JOIN racks r ON r.id = s.rack_id "
        "JOIN zones z ON z.id = r.zone_id WHERE m.movement_type = 'receipt' GROUP BY 1, 2",
    )
    main_zone = put_away.sort_values("units").groupby("product_id")["zone_type"].last()
    storage = (
        products["id"]
        .map(main_zone)
        .map(lambda zone: STORAGE_TYPES.index(zone) if zone in ("cold", "hazardous") else 0)
    )
    names = sorted(products["category"].unique())
    zone_index = bins["zone_type"].map(lambda z: ZONE_TYPES.index(z) if z in ZONE_TYPES else -1)
    return Layout(
        product_ids=products["id"].to_numpy(),
        weight_kg=products["weight_kg"].to_numpy(float) / SCALE["weight_kg"],
        volume_cm3=products["volume"].to_numpy(float) / SCALE["length_cm"] ** 3,
        category=products["category"].map({n: i for i, n in enumerate(names)}).to_numpy(),
        category_names=names,
        storage=storage.to_numpy(int),
        bin_ids=bins["id"].to_numpy(),
        bin_warehouse=bins["warehouse_id"].to_numpy(),
        bin_zone=zone_index.to_numpy(int),
        bin_level=bins["level"].to_numpy(int),
        bin_distance=bins["distance"].to_numpy(float) / SCALE["distance_m"],
        bin_max_kg=bins["max_weight_kg"].to_numpy(float) / SCALE["weight_kg"],
        bin_max_cm3=bins["max_volume_cm3"].to_numpy(float),
        warehouse_ids=np.unique(bins["warehouse_id"].to_numpy()),
    )


def load_picks(
    engine: Engine, layout: Layout, first: date, days: int
) -> tuple[np.ndarray, np.ndarray]:
    """(warehouses, products, days) order lines (picks) and units per day."""
    frame = read_frame(
        engine,
        "SELECT o.warehouse_id, oi.product_id, date(o.created_at) AS day, COUNT(*) AS lines, "
        "SUM(oi.quantity) AS units FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "WHERE o.warehouse_id IS NOT NULL GROUP BY 1, 2, 3",
    )
    w = np.searchsorted(layout.warehouse_ids, frame["warehouse_id"].to_numpy())
    p = np.searchsorted(layout.product_ids, frame["product_id"].to_numpy())
    d = (pd.to_datetime(frame["day"]) - pd.Timestamp(first)).dt.days.to_numpy()
    keep = (d >= 0) & (d < days)
    shape = (len(layout.warehouse_ids), len(layout.product_ids), days)
    lines, units = np.zeros(shape, "float32"), np.zeros(shape, "float32")
    lines[w[keep], p[keep], d[keep]] = frame["lines"].to_numpy()[keep]
    units[w[keep], p[keep], d[keep]] = frame["units"].to_numpy()[keep]
    return lines, units


def current_slots(engine: Engine, layout: Layout, until: date) -> dict[tuple[int, int], int]:
    """(warehouse index, product index) -> bin index holding most of its stock at the end of
    `until` (where it is picked from today)."""
    stock = read_frame(
        engine,
        "SELECT product_id, bin_id, SUM(on_hand_delta) AS units FROM inventory_movements "
        f"WHERE date(created_at) <= '{until.isoformat()}' GROUP BY 1, 2 HAVING units > 0",
    )
    bin_row = {b: i for i, b in enumerate(layout.bin_ids)}
    stock = stock[stock["bin_id"].isin(bin_row)]
    stock = stock.assign(row=stock["bin_id"].map(bin_row))
    stock = stock[layout.bin_zone[stock["row"]] >= 0]  # not the returns zone
    best = stock.sort_values("units").groupby(["product_id", "row"]).last().reset_index()
    best = best.assign(wh=layout.bin_warehouse[best["row"]]).sort_values("units")
    top = best.groupby(["wh", "product_id"]).last().reset_index()
    wh_index = {w: i for i, w in enumerate(layout.warehouse_ids)}
    product_row = {p: i for i, p in enumerate(layout.product_ids)}
    return {
        (wh_index[r.wh], product_row[r.product_id]): int(r.row)
        for r in top.itertuples()
        if r.product_id in product_row
    }


def pick_seconds(
    layout: Layout, product: np.ndarray, bins: np.ndarray, units_per_pick
) -> np.ndarray:
    """Estimated seconds per pick of `product` rows in `bins` (same shape or broadcast)."""
    level = layout.bin_level[bins]
    weight = layout.weight_kg[product]
    return (
        2 * layout.bin_distance[bins] / WALK_SPEED_M_PER_S
        + SECONDS_PER_PICK
        + SECONDS_PER_UNIT * units_per_pick
        + SECONDS_PER_KG_PER_LEVEL * weight * np.maximum(level - 2, 0)
        + LADDER_SECONDS * (level >= LADDER_LEVEL)
    )


def face_need(layout: Layout, units_per_day: np.ndarray, product: np.ndarray):
    """Weight (kg) and volume (cm³) of a pick face: FACE_DAYS of units, at least one, and
    no more than fits in the largest bin the product may use (fast, bulky products are
    then simply refilled more often)."""
    product = np.asarray(product, int)
    units = np.maximum(np.ceil(np.asarray(units_per_day) * FACE_DAYS), 1)
    weight, volume = layout.weight_kg[product], layout.volume_cm3[product]
    fits = np.array(
        [
            max(
                1.0,
                np.max(
                    np.minimum(
                        layout.bin_max_kg[layout.allowed(p)] // max(weight[i], 1e-9),
                        layout.bin_max_cm3[layout.allowed(p)] // max(volume[i], 1e-9),
                    ),
                    initial=1.0,
                ),
            )
            for i, p in enumerate(product)
        ]
    )
    units = np.minimum(units, fits)
    return units * weight, units * volume


@dataclass
class ProductState:
    """Per warehouse and product at a snapshot day: what is known from the past."""

    picks_28: np.ndarray  # (warehouses, products) picks per day, last 28 days
    picks_90: np.ndarray
    units_28: np.ndarray  # units per day, last 28 days
    units_per_pick: np.ndarray
    season: np.ndarray  # last year's coming 28 days vs its previous 90 (1 = no data)


def product_state(lines: np.ndarray, units: np.ndarray, day: int) -> ProductState:
    """Known on the evening of day index `day` (inclusive)."""
    if day < 89:
        raise ValueError("a snapshot needs 90 days of history")

    def mean(values: np.ndarray, start: int, end: int) -> np.ndarray:
        return values[:, :, max(start, 0) : end + 1].mean(axis=2)

    picks_28, picks_90 = mean(lines, day - 27, day), mean(lines, day - 89, day)
    units_28 = mean(units, day - 27, day)
    total_units = units[:, :, day - 89 : day + 1].sum(axis=2)
    total_lines = lines[:, :, day - 89 : day + 1].sum(axis=2)
    per_pick = np.where(total_lines > 0, total_units / np.maximum(total_lines, 1), 1.0)
    year_ago = day - 365
    if year_ago - 89 >= 0:
        ahead = mean(lines, year_ago + 1, year_ago + 28)
        before = mean(lines, year_ago - 89, year_ago)
        season = (ahead + 0.05) / (before + 0.05)
    else:
        season = np.ones_like(picks_28)
    return ProductState(picks_28, picks_90, units_28, per_pick, np.clip(season, 0.2, 5))


PRODUCT_NUMERIC = (
    "log_picks_28",
    "log_picks_90",
    "trend",
    "season",
    "log_units_per_pick",
    "weight_kg",
    "log_volume",
    "heavy",
)
BIN_NUMERIC = ("distance_m", "level", "log_max_cm3", "max_kg")


def pair_features(
    layout: Layout, state: ProductState, warehouse: int, products: np.ndarray, bins: np.ndarray
) -> dict[str, np.ndarray]:
    """Model inputs for (product, bin) pairs of one warehouse (equal-length index arrays)."""
    p28, p90 = state.picks_28[warehouse, products], state.picks_90[warehouse, products]
    weight = layout.weight_kg[products]
    product_numeric = np.stack(
        [
            np.log1p(p28),
            np.log1p(p90),
            np.log((p28 + 0.05) / (p90 + 0.05)),
            state.season[warehouse, products],
            np.log1p(state.units_per_pick[warehouse, products]),
            weight,
            np.log1p(layout.volume_cm3[products]),
            (weight >= HEAVY_KG).astype(float),
        ],
        axis=1,
    )
    level = layout.bin_level[bins]
    bin_numeric = np.stack(
        [
            layout.bin_distance[bins],
            level,
            np.log1p(layout.bin_max_cm3[bins]),
            layout.bin_max_kg[bins],
        ],
        axis=1,
    )
    n = len(products)
    categorical = np.zeros((n, len(layout.category_names) + len(ZONE_TYPES)), "float32")
    categorical[np.arange(n), layout.category[products]] = 1
    categorical[np.arange(n), len(layout.category_names) + layout.bin_zone[bins]] = 1
    # Wide part: speed bucket x distance bucket, heavy x level.
    speed = np.digitize(p28, (0.05, 0.2, 0.5, 1.0, 2.0))  # 0..5
    distance = np.digitize(layout.bin_distance[bins], (10, 20, 35, 50))  # 0..4
    wide = np.zeros((n, 6 * 5 + 2 * 4), "float32")
    wide[np.arange(n), speed * 5 + distance] = 1
    wide[np.arange(n), 30 + (weight >= HEAVY_KG) * 4 + np.clip(level, 1, 4) - 1] = 1
    return {
        "product": product_numeric.astype("float32"),
        "bin": bin_numeric.astype("float32"),
        "categorical": categorical,
        "wide": wide,
    }
