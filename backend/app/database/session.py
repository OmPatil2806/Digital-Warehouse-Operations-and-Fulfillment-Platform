"""Database engine, session factory and FastAPI session dependency."""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine.

    For SQLite this also:
    - allows the connection to be used across FastAPI worker threads,
    - creates the database folder if needed,
    - enables foreign-key enforcement (off by default in SQLite).
    """
    settings = get_settings()
    url = database_url or settings.sqlalchemy_database_url
    is_sqlite = url.startswith("sqlite")

    connect_args = {"check_same_thread": False} if is_sqlite else {}
    if is_sqlite and database_url is None:
        settings.ensure_sqlite_directory()

    new_engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)

    if is_sqlite:

        @event.listens_for(new_engine, "connect")
        def _on_sqlite_connect(dbapi_connection, _connection_record) -> None:
            # Python's sqlite3 driver normally starts transactions itself (late, and
            # not for every statement), which breaks SAVEPOINTs and rollbacks. Turning
            # that off lets SQLAlchemy emit BEGIN explicitly (see the "begin" hook below).
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        @event.listens_for(new_engine, "begin")
        def _on_sqlite_begin(connection) -> None:
            connection.exec_driver_sql("BEGIN")

    return new_engine


engine = build_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection(db: Session) -> bool:
    """Return True if a trivial query succeeds on the given session."""
    try:
        db.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.warning("Database health check failed: %s", exc.__class__.__name__)
        return False
