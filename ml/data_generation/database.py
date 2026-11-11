"""Create the target database and write generated rows in batches.

The generator writes straight into the tables with bulk INSERT statements (no ORM
objects, no audit rows): this is historic data, and it is many times faster. The
schema comes from the backend's Alembic migrations, so the result is exactly the
application's database; foreign keys are enforced while writing.
"""

from collections import Counter
from collections.abc import Iterable, Iterator
from itertools import islice
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, Table, func, select

from app import models  # noqa: F401  (registers every table)
from app.database.session import build_engine

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_DATABASE = PROJECT_ROOT / "database" / "warehouse_synthetic.db"


class GenerationError(Exception):
    """A problem the user can fix (shown without a traceback)."""


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def prepare_database(path: Path, *, replace: bool = False) -> Engine:
    """A migrated, empty database at `path` (an existing file only with `replace`)."""
    if path.exists():
        if not replace:
            raise GenerationError(
                f"{path} already exists. Use --replace to delete it and generate again."
            )
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlite_url(path))
    command.upgrade(config, "head")
    return build_engine(sqlite_url(path))


def batched(rows: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    iterator = iter(rows)
    while batch := list(islice(iterator, size)):
        yield batch


class BatchWriter:
    """Inserts rows table by table in batches of `batch_size`; counts what it wrote."""

    def __init__(self, engine: Engine, batch_size: int) -> None:
        self.engine = engine
        self.batch_size = batch_size
        self.counts: Counter[str] = Counter()

    def insert(self, table: Table, rows: Iterable[dict[str, Any]]) -> int:
        written = 0
        with self.engine.begin() as connection:
            for batch in batched(rows, self.batch_size):
                connection.execute(table.insert(), batch)
                written += len(batch)
        self.counts[table.name] += written
        return written

    def count(self, table: Table) -> int:
        with self.engine.connect() as connection:
            return int(connection.scalar(select(func.count()).select_from(table)) or 0)
