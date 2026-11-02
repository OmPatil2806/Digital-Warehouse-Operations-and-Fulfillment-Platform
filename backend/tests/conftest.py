"""Shared pytest fixtures.

Every test run uses its own temporary SQLite database, so tests never touch
the real `database/warehouse.db` file.
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
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_DB_DIR / 'test.db').as_posix()}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database.session import build_engine, get_db  # noqa: E402
from app.main import app  # noqa: E402


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove the temporary test database folder after the whole test run."""
    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    """Engine bound to the temporary test database, with all tables created."""
    engine = build_engine(get_settings().sqlalchemy_database_url)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    """A database session for one test."""
    session = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI test client whose requests use the test database session."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
