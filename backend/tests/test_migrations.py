"""Tests that the Alembic migrations are complete and reversible."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401  (registers all tables on Base.metadata)
from app.database.base import Base
from tests.conftest import make_alembic_config

AUTH_TABLES = {"users", "roles", "user_roles", "refresh_tokens"}
CATALOG_TABLES = {"categories", "products", "suppliers", "supplier_products"}
WAREHOUSE_TABLES = {"warehouses", "zones", "racks", "shelves", "bins"}
INVENTORY_TABLES = {
    "inventory",
    "inventory_movements",
    "stock_transfers",
    "stock_adjustments",
    "stock_reservations",
    "cycle_counts",
    "cycle_count_lines",
}
AUDIT_TABLES = {"audit_logs", "alerts"}
ORDER_TABLES = {"customers", "orders", "order_items", "order_status_history", "picking_tasks"}
ALL_TABLES = (
    AUTH_TABLES | CATALOG_TABLES | WAREHOUSE_TABLES | INVENTORY_TABLES | AUDIT_TABLES | ORDER_TABLES
)


def _url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"


def test_upgrade_and_downgrade_round_trip(tmp_path: Path) -> None:
    url = _url(tmp_path)
    config = make_alembic_config(url)
    engine = create_engine(url)

    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) >= ALL_TABLES

    with engine.connect() as connection:
        triggers = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).scalars()
        assert set(triggers) >= {
            "inventory_movements_no_update",
            "inventory_movements_no_delete",
            "audit_logs_no_update",
            "audit_logs_no_delete",
        }

    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}

    command.upgrade(config, "head")  # can be applied again after a downgrade
    assert set(inspect(engine).get_table_names()) >= ALL_TABLES
    engine.dispose()


def test_models_match_migrations(tmp_path: Path) -> None:
    """Fails if a model was changed without creating a migration."""
    url = _url(tmp_path)
    command.upgrade(make_alembic_config(url), "head")
    engine = create_engine(url)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    engine.dispose()

    assert differences == []


def test_constraint_and_index_names_are_unique_in_the_models() -> None:
    """Two constraints with the same name shadow each other (this once made the drift test
    flaky). The naming convention only uses the FIRST column of a unique constraint, so
    multi-column constraints that start with the same column need explicit names."""
    names = [
        item.name
        for table in Base.metadata.tables.values()
        for item in [*table.constraints, *table.indexes]
        if item.name
    ]
    duplicates = sorted({name for name in names if names.count(name) > 1})

    assert duplicates == []


def test_constraint_names_are_unique_in_the_migrated_database(tmp_path: Path) -> None:
    url = _url(tmp_path)
    command.upgrade(make_alembic_config(url), "head")
    engine = create_engine(url)
    inspector = inspect(engine)

    for table in inspector.get_table_names():
        names = [c["name"] for c in inspector.get_unique_constraints(table) if c["name"]]
        assert len(names) == len(set(names)), f"duplicate unique constraint names in {table}"
    engine.dispose()
