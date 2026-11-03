"""Shared pytest fixtures.

Every test run uses its own temporary SQLite database, so tests never touch
the real `database/warehouse.db` file. The schema is built by running the real
Alembic migrations, and every test runs inside a transaction that is rolled back
afterwards, so tests cannot affect each other.
"""

import os
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

# Must be set BEFORE the app is imported: real environment variables take priority
# over the project `.env`, and the module-level engine is created at import time.
_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="warehouse-tests-"))
os.environ["APP_ENV"] = "test"
os.environ["BCRYPT_ROUNDS"] = "4"  # minimum cost: keeps password-hashing tests fast
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_DB_DIR / 'test.db').as_posix()}"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.database.session import build_engine, get_db  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def make_alembic_config(database_url: str) -> Config:
    """Alembic config pointing at the given database (without touching logging setup)."""
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove the temporary test database folder after the whole test run."""
    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    """Engine bound to the temporary test database, migrated to the latest schema."""
    database_url = get_settings().sqlalchemy_database_url
    command.upgrade(make_alembic_config(database_url), "head")
    engine = build_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    """A database session for one test; everything it writes is rolled back afterwards."""
    connection = test_engine.connect()
    transaction = connection.begin()
    # Commits inside the test only release a SAVEPOINT; the outer transaction is rolled back.
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI test client whose requests use the test database session."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
