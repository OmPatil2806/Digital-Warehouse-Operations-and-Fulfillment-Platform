"""HTTP tests for /api/v1/auth/* and role-based access control."""

from collections.abc import Generator
from datetime import timedelta
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.permissions import require_roles
from app.core.security import create_access_token
from app.models.user import RoleName, User
from tests.factories import DEFAULT_PASSWORD, create_user

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


def login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def set_cookie_header(response) -> str:
    return response.headers.get("set-cookie", "")


def replace_refresh_cookie(client: TestClient, value: str | None) -> None:
    """Make the client send exactly this refresh-token cookie (simulates a replay)."""
    client.cookies.clear()
    if value is not None:
        client.cookies.set("refresh_token", value)


# -------------------------------------------------------------------------- login


def test_login_returns_access_token_and_sets_refresh_cookie(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session, "login@example.com")

    response = login(client, "LOGIN@example.com")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    assert "refresh_token" not in body  # only in the cookie

    cookie = set_cookie_header(response).lower()
    assert cookie.startswith("refresh_token=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api/v1/auth" in cookie
    assert "max-age=" in cookie
    assert "secure" not in cookie  # plain http is allowed in the test environment


@pytest.mark.parametrize(
    ("email", "password"),
    [("known@example.com", "Wrong-passw0rd"), ("unknown@example.com", DEFAULT_PASSWORD)],
)
def test_login_failure_is_generic_401(
    client: TestClient, db_session: Session, email: str, password: str
) -> None:
    create_user(db_session, "known@example.com")

    response = login(client, email, password)

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert "set-cookie" not in response.headers


def test_login_deactivated_account(client: TestClient, db_session: Session) -> None:
    create_user(db_session, "inactive@example.com", is_active=False)

    response = login(client, "inactive@example.com")

    assert response.status_code == 401
    assert response.json()["detail"] == "This account has been deactivated"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "x"},
        {"email": "a@example.com", "password": ""},
        {"email": "a@example.com"},
        {},
    ],
)
def test_login_validation_errors_return_422(client: TestClient, payload: dict) -> None:
    assert client.post(LOGIN, json=payload).status_code == 422


# ----------------------------------------------------------------------------- me


def test_me_returns_the_current_user(client: TestClient, db_session: Session) -> None:
    create_user(db_session, "me@example.com", full_name="Me Myself", roles=(RoleName.STAFF,))
    token = login(client, "me@example.com").json()["access_token"]

    response = client.get(ME, headers=bearer(token))

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert body["full_name"] == "Me Myself"
    assert body["roles"] == ["staff"]
    assert body["last_login_at"] is not None
    assert "hashed_password" not in body


def test_me_without_token_is_401(client: TestClient) -> None:
    response = client.get(ME)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer"},
    ],
)
def test_me_with_invalid_authorization_is_401(client: TestClient, headers: dict) -> None:
    assert client.get(ME, headers=headers).status_code == 401


def test_me_with_expired_token_is_401(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session, "old@example.com")
    token = create_access_token(user.id, expires_delta=timedelta(seconds=-1))

    response = client.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json() == {"detail": "Token has expired"}


def test_access_token_stops_working_when_user_is_deactivated(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session, "soon-gone@example.com")
    token = login(client, "soon-gone@example.com").json()["access_token"]
    user.is_active = False
    db_session.commit()

    response = client.get(ME, headers=bearer(token))

    assert response.status_code == 401
    assert response.json() == {"detail": "User not found or inactive"}


def test_token_for_deleted_user_is_401(client: TestClient) -> None:
    token = create_access_token(987_654)

    assert client.get(ME, headers=bearer(token)).status_code == 401


# ------------------------------------------------------------------------ refresh


def test_refresh_returns_new_tokens_and_rotates_cookie(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session, "refresh@example.com")
    first = login(client, "refresh@example.com")
    first_cookie = client.cookies.get("refresh_token")

    response = client.post(REFRESH)  # the test client sends the cookie automatically

    assert response.status_code == 200
    new_token = response.json()["access_token"]
    assert new_token != first.json()["access_token"]
    assert client.cookies.get("refresh_token") not in (None, first_cookie)
    assert client.get(ME, headers=bearer(new_token)).status_code == 200


def test_refresh_without_cookie_is_401(client: TestClient) -> None:
    response = client.post(REFRESH)

    assert response.status_code == 401
    assert response.json() == {"detail": "Refresh token missing"}


def test_reused_refresh_cookie_is_rejected_and_cleared(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session, "replay@example.com")
    login(client, "replay@example.com")
    old_cookie = client.cookies.get("refresh_token")
    assert client.post(REFRESH).status_code == 200  # rotates; old cookie is now revoked

    new_cookie = client.cookies.get("refresh_token")
    replace_refresh_cookie(client, old_cookie)
    response = client.post(REFRESH)

    assert response.status_code == 401
    assert "max-age=0" in set_cookie_header(response).lower()  # browser deletes the cookie
    # Reuse revoked every session, including the newest one:
    replace_refresh_cookie(client, new_cookie)
    assert client.post(REFRESH).status_code == 401


# ------------------------------------------------------------------------- logout


def test_logout_clears_cookie_and_revokes_session(client: TestClient, db_session: Session) -> None:
    create_user(db_session, "logout@example.com")
    login(client, "logout@example.com")
    cookie = client.cookies.get("refresh_token")

    response = client.post(LOGOUT)

    assert response.status_code == 204
    assert "max-age=0" in set_cookie_header(response).lower()
    replace_refresh_cookie(client, cookie)
    assert client.post(REFRESH).status_code == 401  # revoked on the server, not just deleted


def test_logout_without_cookie_still_succeeds(client: TestClient) -> None:
    assert client.post(LOGOUT).status_code == 204


# ---------------------------------------------------------------- role-based access


@pytest.fixture()
def rbac_client(db_session: Session) -> Generator[TestClient, None, None]:
    """A small throwaway app with role-protected endpoints, sharing the test database."""
    app = FastAPI()

    @app.get("/managers-only", dependencies=[Depends(require_roles(RoleName.MANAGER))])
    def managers_only() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/staff-or-manager")
    def staff_or_manager(
        user: Annotated[User, Depends(require_roles(RoleName.STAFF, RoleName.MANAGER))],
    ) -> dict[str, str]:
        return {"email": user.email}

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("roles", "managers_only", "staff_or_manager"),
    [
        ((RoleName.ADMIN,), 200, 200),  # admins are allowed everywhere
        ((RoleName.MANAGER,), 200, 200),
        ((RoleName.STAFF,), 403, 200),
        ((RoleName.CUSTOMER,), 403, 403),
        ((RoleName.CUSTOMER, RoleName.STAFF), 403, 200),  # any matching role is enough
    ],
)
def test_require_roles(
    rbac_client: TestClient,
    db_session: Session,
    roles: tuple[RoleName, ...],
    managers_only: int,
    staff_or_manager: int,
) -> None:
    user = create_user(db_session, "rbac@example.com", roles=roles)
    headers = bearer(create_access_token(user.id))

    first = rbac_client.get("/managers-only", headers=headers)
    second = rbac_client.get("/staff-or-manager", headers=headers)

    assert first.status_code == managers_only
    assert second.status_code == staff_or_manager
    if first.status_code == 403:
        assert first.json() == {"detail": "You do not have permission to perform this action"}
    if second.status_code == 200:
        assert second.json() == {"email": "rbac@example.com"}


def test_require_roles_without_token_is_401_not_403(rbac_client: TestClient) -> None:
    assert rbac_client.get("/managers-only").status_code == 401


def test_require_roles_needs_at_least_one_role() -> None:
    with pytest.raises(ValueError):
        require_roles()
