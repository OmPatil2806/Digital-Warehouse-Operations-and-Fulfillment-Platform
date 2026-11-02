"""Tests for the /api/v1/health endpoint and basic API wiring."""

from collections.abc import Generator
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.database.session import build_engine, get_db
from app.main import app

HEALTH_URL = "/api/v1/health"


def test_health_returns_200_and_ok(client: TestClient) -> None:
    response = client.get(HEALTH_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_health_response_structure(client: TestClient) -> None:
    body = client.get(HEALTH_URL).json()
    settings = get_settings()

    assert set(body) == {"status", "app_name", "version", "environment", "database", "timestamp"}
    assert body["app_name"] == settings.app_name
    assert body["version"] == settings.app_version
    assert body["environment"] == "test"
    datetime.fromisoformat(body["timestamp"])  # raises if not a valid ISO timestamp


def test_health_reports_degraded_when_database_unavailable(
    client: TestClient, tmp_path: Path
) -> None:
    # A SQLite file inside a folder that does not exist cannot be opened.
    broken_url = f"sqlite:///{(tmp_path / 'missing-dir' / 'x.db').as_posix()}"
    broken_engine = build_engine(broken_url)
    broken_session_factory = sessionmaker(bind=broken_engine)

    def _broken_get_db() -> Generator[Session, None, None]:
        session = broken_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _broken_get_db
    response = client.get(HEALTH_URL)
    broken_engine.dispose()

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "unavailable"


def test_openapi_docs_are_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert HEALTH_URL in schema["paths"]


def test_unknown_route_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/does-not-exist").status_code == 404


def test_cors_allows_configured_frontend_origin(client: TestClient) -> None:
    origin = get_settings().cors_origin_list[0]
    response = client.options(
        HEALTH_URL,
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
