"""Tests for settings resolution and the database session layer."""

from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings
from app.database.session import check_database_connection


def test_relative_sqlite_path_resolves_to_project_root() -> None:
    settings = Settings(database_url="sqlite:///./database/warehouse.db")
    expected = (PROJECT_ROOT / "database" / "warehouse.db").resolve().as_posix()

    assert settings.sqlalchemy_database_url == f"sqlite:///{expected}"


def test_absolute_sqlite_path_is_unchanged(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'abs.db').as_posix()}"

    assert Settings(database_url=url).sqlalchemy_database_url == url


def test_in_memory_and_non_sqlite_urls_are_unchanged() -> None:
    memory = "sqlite:///:memory:"
    postgres = "postgresql://user:pass@localhost/db"

    assert Settings(database_url=memory).sqlalchemy_database_url == memory
    assert Settings(database_url=postgres).sqlalchemy_database_url == postgres
    assert Settings(database_url=postgres).is_sqlite is False


def test_cors_origins_are_parsed_from_comma_separated_string() -> None:
    settings = Settings(cors_origins=" http://localhost:5173 , http://127.0.0.1:5173 ,")

    assert settings.cors_origin_list == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_check_database_connection_succeeds(db_session: Session) -> None:
    assert check_database_connection(db_session) is True


def test_sqlite_foreign_keys_are_enforced(test_engine: Engine) -> None:
    with test_engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
