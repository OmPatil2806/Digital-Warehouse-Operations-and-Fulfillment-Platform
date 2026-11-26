"""Security hardening (Phase 10): login required everywhere, failed-login limits,
security headers, CORS, clean server errors and refused unsafe settings."""

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.login_throttle import LoginThrottle
from app.core.security_headers import add_security_headers
from app.exceptions.handlers import register_exception_handlers
from app.main import API_V1_PREFIX, app
from app.models.user import RoleName
from tests.factories import DEFAULT_PASSWORD, create_user

# The only endpoints anyone may call without logging in.
PUBLIC = {
    ("GET", "/health"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
}


def _operations() -> list[tuple[str, str, dict]]:
    """(method, path under /api/v1, OpenAPI operation) of every API endpoint."""
    return [
        (method.upper(), path.removeprefix(API_V1_PREFIX), operation)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(API_V1_PREFIX)
        for method, operation in operations.items()
    ]


# ------------------------------------------------------------------ login required
def test_every_endpoint_except_the_public_ones_requires_login() -> None:
    """Every endpoint that depends on the logged-in user carries the Bearer security
    requirement in the API description; a new endpoint without it fails this test."""
    operations = _operations()
    assert len(operations) > 100  # the check really looked at the API
    unprotected = {(m, p) for m, p, op in operations if not op.get("security")}
    assert unprotected == PUBLIC


def test_endpoints_without_a_body_answer_401_without_a_token(client: TestClient) -> None:
    checked = 0
    for method, path, operation in _operations():
        if (method, path) in PUBLIC or "requestBody" in operation:
            continue
        response = client.request(method, API_V1_PREFIX + _fill_ids(path))
        assert response.status_code == 401, (method, path)
        checked += 1
    assert checked > 60


def _fill_ids(path: str) -> str:
    parts = [("1" if p.startswith("{") else p) for p in path.split("/")]
    return "/".join(parts)


# ------------------------------------------------------------ failed-login limits
def login(client: TestClient, email: str, password: str):
    return client.post(f"{API_V1_PREFIX}/auth/login", json={"email": email, "password": password})


def test_an_account_is_locked_after_five_wrong_passwords(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session, "maya@example.com", roles=(RoleName.MANAGER,))
    for _ in range(4):
        assert login(client, "maya@example.com", "wrong-password").status_code == 401
    assert login(client, "maya@example.com", DEFAULT_PASSWORD).status_code == 200  # resets

    for _ in range(5):
        assert login(client, "maya@example.com", "wrong-password").status_code == 401
    locked = login(client, "MAYA@example.com", DEFAULT_PASSWORD)  # even the right one
    assert locked.status_code == 429
    assert "Too many failed login attempts" in locked.json()["detail"]
    assert 0 < int(locked.headers["Retry-After"]) <= 15 * 60
    # Another account can still log in.
    create_user(db_session, "sam@example.com", roles=(RoleName.STAFF,))
    assert login(client, "sam@example.com", DEFAULT_PASSWORD).status_code == 200


def test_unknown_emails_are_counted_like_real_ones(client: TestClient) -> None:
    """Otherwise the lockout would reveal which accounts exist."""
    for _ in range(5):
        assert login(client, "nobody@example.com", "guess").status_code == 401
    assert login(client, "nobody@example.com", "guess").status_code == 429


def test_lockout_ends_after_the_lockout_time() -> None:
    now = [1000.0]
    throttle = LoginThrottle(
        max_failures=3,
        window=timedelta(minutes=10),
        lockout=timedelta(minutes=5),
        clock=lambda: now[0],
    )
    for _ in range(3):
        throttle.failed("a@example.com", None)
    assert throttle.retry_after("a@example.com", None) == 300
    now[0] += 299
    assert throttle.retry_after("a@example.com", None) == 1
    now[0] += 1
    assert throttle.retry_after("a@example.com", None) == 0


def test_old_failures_fall_out_of_the_window() -> None:
    now = [0.0]
    throttle = LoginThrottle(max_failures=3, window=timedelta(minutes=10), clock=lambda: now[0])
    throttle.failed("a@example.com", None)
    throttle.failed("a@example.com", None)
    now[0] += 11 * 60  # the two failures are older than the window
    throttle.failed("a@example.com", None)
    assert throttle.retry_after("a@example.com", None) == 0


def test_one_client_trying_many_accounts_is_stopped() -> None:
    throttle = LoginThrottle(max_failures=2, ip_factor=3, clock=lambda: 0.0)
    for n in range(5):
        throttle.failed(f"user{n}@example.com", "10.0.0.7")
    assert throttle.retry_after("someone@example.com", "10.0.0.7") == 0  # 5 < 2 x 3
    throttle.failed("user9@example.com", "10.0.0.7")
    assert throttle.retry_after("someone@example.com", "10.0.0.7") > 0  # this client
    assert throttle.retry_after("someone@example.com", "10.0.0.8") == 0  # others are fine


# ---------------------------------------------------------------- response headers
def test_security_headers_on_api_responses(client: TestClient) -> None:
    response = client.get(f"{API_V1_PREFIX}/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in response.headers  # plain http in tests
    # The interactive docs load scripts from a CDN: no strict CSP there.
    assert "Content-Security-Policy" not in client.get("/docs").headers


def test_auth_responses_are_never_cached(client: TestClient) -> None:
    response = login(client, "nobody@example.com", "x")
    assert response.headers["Cache-Control"] == "no-store"


def test_https_sites_get_strict_transport_security() -> None:
    site = FastAPI()
    add_security_headers(site, https=True, auth_prefix="/auth")
    site.get("/ping")(lambda: {"ok": True})
    assert "max-age=31536000" in TestClient(site).get("/ping").headers["Strict-Transport-Security"]


# -------------------------------------------------------------------------- CORS
def test_cors_allows_only_the_web_app(client: TestClient) -> None:
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }
    allowed = client.options(
        f"{API_V1_PREFIX}/orders", headers={"Origin": "http://localhost:5173", **preflight}
    )
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert allowed.headers["Access-Control-Allow-Credentials"] == "true"
    other = client.options(
        f"{API_V1_PREFIX}/orders", headers={"Origin": "https://evil.example", **preflight}
    )
    assert "Access-Control-Allow-Origin" not in other.headers


@pytest.mark.parametrize("origins", ["*", "http://localhost:5173,*", "localhost:5173"])
def test_wildcard_or_malformed_cors_origins_are_refused(origins: str) -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(cors_origins=origins)


def test_production_refuses_the_default_secret_key() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="production")
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="production", secret_key="too-short")
    assert Settings(app_env="production", secret_key="x" * 40).refresh_cookie_secure


# ------------------------------------------------------------------ server errors
def test_unexpected_errors_are_a_clean_json_message(caplog: pytest.LogCaptureFixture) -> None:
    site = FastAPI()
    register_exception_handlers(site)

    @site.get("/boom")
    def boom() -> None:
        raise RuntimeError("SELECT secret FROM users -- /srv/app/db.py line 42")

    response = TestClient(site, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail.startswith("Something went wrong on the server")
    assert "SELECT" not in response.text and "db.py" not in response.text  # nothing leaks
    reference = detail.rsplit(" ", 1)[-1].rstrip(")")
    assert reference in caplog.text and "RuntimeError" in caplog.text  # logged in full
