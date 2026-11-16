"""Reading the generated database for training (extraction step of 12.1).

Training reads the operational tables of the synthetic database (by default
database/warehouse_synthetic.db, made by scripts/generate_data.py) with plain SQL into
pandas. Money, weights and lengths are stored as scaled integers in SQLite
(app.database.types.ScaledDecimal); `SCALE` turns them back into numbers.
"""

import hashlib
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, create_engine, inspect

from data_generation.database import DEFAULT_DATABASE, sqlite_url

# Stored integer -> real value: divide by these (see the ScaledDecimal columns).
SCALE = {"money": 100, "weight_kg": 1000, "length_cm": 10, "distance_m": 10}

# The tables whose sizes identify a dataset (with its last order date and a checksum).
FINGERPRINT_TABLES = ("products", "customers", "bins", "orders", "order_items")


class DatasetError(RuntimeError):
    """The training database is missing or not a generated dataset."""


def open_dataset(path: Path = DEFAULT_DATABASE) -> Engine:
    """An engine on a generated database; clear errors when it is missing or empty."""
    if not path.exists():
        raise DatasetError(
            f"No dataset at {path}. Generate one first: python scripts/generate_data.py"
        )
    engine = create_engine(sqlite_url(path))
    if not inspect(engine).has_table("orders"):
        engine.dispose()
        raise DatasetError(f"{path} is not a warehouse database (no orders table)")
    return engine


def read_frame(engine: Engine, sql: str, *, dates: tuple[str, ...] = ()) -> pd.DataFrame:
    """A query as a DataFrame; `dates` columns are parsed as UTC timestamps."""
    with engine.connect() as connection:
        frame = pd.read_sql_query(sql, connection)
    for column in dates:
        frame[column] = pd.to_datetime(frame[column], utc=True, format="ISO8601")
    return frame


def history_range(engine: Engine) -> tuple[date, date]:
    """First and last day with orders."""
    frame = read_frame(
        engine, "SELECT MIN(date(created_at)) AS first, MAX(date(created_at)) AS last FROM orders"
    )
    first, last = frame.iloc[0]
    if first is None:
        raise DatasetError("the dataset has no orders")
    return date.fromisoformat(first), date.fromisoformat(last)


def dataset_version(engine: Engine) -> str:
    """A short name that identifies the data a model was trained on, e.g.
    "orders499179-to2026-11-10-3f9a1c2e". The same generated dataset always gives the
    same name; any other dataset (size, seed, end date) a different one."""
    with engine.connect() as connection:
        counts = [
            connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one()
            for table in FINGERPRINT_TABLES
        ]
        checksum_source = connection.exec_driver_sql(
            "SELECT COALESCE(SUM(subtotal), 0), COALESCE(SUM(customer_id * id), 0) FROM orders"
        ).one()
    _, last = history_range(engine)
    digest = hashlib.sha256(repr((counts, tuple(checksum_source))).encode()).hexdigest()[:8]
    return f"orders{counts[3]}-to{last.isoformat()}-{digest}"
