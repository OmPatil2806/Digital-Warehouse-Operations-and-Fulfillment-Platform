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
ALL_TABLES = AUTH_TABLES | CATALOG_TABLES


def _url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"


def test_upgrade_and_downgrade_round_trip(tmp_path: Path) -> None:
    url = _url(tmp_path)
    config = make_alembic_config(url)
    engine = create_engine(url)

    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) >= ALL_TABLES

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
