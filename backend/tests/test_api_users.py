"""HTTP tests for the admin-only /api/v1/users endpoints and their safety rules."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.user import RoleName, User
from app.schemas.user import UserUpdate
from app.services.user_service import UserRuleViolationError, UserService
from tests.factories import DEFAULT_PASSWORD, create_user

USERS = "/api/v1/users"
NEW_USER = {"email": "New@Example.com", "full_name": "New Person", "password": "Welcome-123"}


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def admin(db_session: Session) -> User:
    return create_user(db_session, "admin@example.com", roles=(RoleName.ADMIN,))


# ----------------------------------------------------------------- access control


@pytest.mark.parametrize("role", [RoleName.MANAGER, RoleName.STAFF, RoleName.CUSTOMER])
def test_non_admins_get_403(client: TestClient, db_session: Session, role: RoleName) -> None:
    user = create_user(db_session, f"{role}@example.com", roles=(role,))
    headers = auth(user)

    assert client.get(USERS, headers=headers).status_code == 403
    assert client.post(USERS, json=NEW_USER, headers=headers).status_code == 403
    assert client.get(f"{USERS}/{user.id}", headers=headers).status_code == 403
    assert client.patch(f"{USERS}/{user.id}", json={}, headers=headers).status_code == 403
    assert client.post(f"{USERS}/{user.id}/deactivate", headers=headers).status_code == 403


def test_anonymous_gets_401(client: TestClient) -> None:
    assert client.get(USERS).status_code == 401
    assert client.post(USERS, json=NEW_USER).status_code == 401


# ------------------------------------------------------------------- create / read


def test_admin_creates_user_who_can_then_log_in(client: TestClient, admin: User) -> None:
    response = client.post(USERS, json={**NEW_USER, "roles": ["staff"]}, headers=auth(admin))

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["roles"] == ["staff"]
    assert body["is_active"] is True
    assert "password" not in body and "hashed_password" not in body

    login = client.post(
        "/api/v1/auth/login", json={"email": "new@example.com", "password": "Welcome-123"}
    )
    assert login.status_code == 200


def test_new_user_defaults_to_customer(client: TestClient, admin: User) -> None:
    response = client.post(USERS, json=NEW_USER, headers=auth(admin))

    assert response.json()["roles"] == ["customer"]


def test_duplicate_email_is_409(client: TestClient, admin: User) -> None:
    client.post(USERS, json=NEW_USER, headers=auth(admin))

    response = client.post(
        USERS, json={**NEW_USER, "email": "NEW@example.com"}, headers=auth(admin)
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "A user with this email already exists"}


@pytest.mark.parametrize(
    "overrides",
    [{"password": "short1"}, {"password": "nodigitshere"}, {"email": "bad"}, {"roles": ["god"]}],
)
def test_invalid_create_is_422(client: TestClient, admin: User, overrides: dict) -> None:
    response = client.post(USERS, json={**NEW_USER, **overrides}, headers=auth(admin))

    assert response.status_code == 422


def test_list_users_is_paginated(client: TestClient, db_session: Session, admin: User) -> None:
    for number in range(4):
        create_user(db_session, f"u{number}@example.com")

    page = client.get(f"{USERS}?offset=1&limit=2", headers=auth(admin)).json()

    assert page["total"] == 5  # admin + 4
    assert page["offset"] == 1
    assert page["limit"] == 2
    assert [user["email"] for user in page["items"]] == ["u0@example.com", "u1@example.com"]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_invalid_pagination_is_422(client: TestClient, admin: User, query: str) -> None:
    assert client.get(f"{USERS}?{query}", headers=auth(admin)).status_code == 422


def test_get_user_and_404(client: TestClient, db_session: Session, admin: User) -> None:
    other = create_user(db_session, "other@example.com")

    assert client.get(f"{USERS}/{other.id}", headers=auth(admin)).json()["email"] == (
        "other@example.com"
    )
    missing = client.get(f"{USERS}/999999", headers=auth(admin))
    assert missing.status_code == 404
    assert missing.json() == {"detail": "User not found"}


# ------------------------------------------------------------------------- update


def test_patch_changes_only_sent_fields(
    client: TestClient, db_session: Session, admin: User
) -> None:
    other = create_user(db_session, "patch@example.com", full_name="Old Name")

    response = client.patch(
        f"{USERS}/{other.id}",
        json={"full_name": "New Name", "roles": ["manager", "staff"]},
        headers=auth(admin),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["full_name"] == "New Name"
    assert body["roles"] == ["manager", "staff"]
    assert body["email"] == "patch@example.com"  # unchanged


def test_patch_email_to_existing_one_is_409(
    client: TestClient, db_session: Session, admin: User
) -> None:
    other = create_user(db_session, "mine@example.com")

    response = client.patch(
        f"{USERS}/{other.id}", json={"email": "admin@example.com"}, headers=auth(admin)
    )

    assert response.status_code == 409


def test_password_change_works_and_ends_existing_sessions(
    client: TestClient, db_session: Session, admin: User
) -> None:
    create_user(db_session, "pw@example.com")
    login = client.post(
        "/api/v1/auth/login", json={"email": "pw@example.com", "password": DEFAULT_PASSWORD}
    )
    old_cookie = client.cookies.get("refresh_token")
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    user_id = me.json()["id"]

    response = client.patch(
        f"{USERS}/{user_id}", json={"password": "Brand-new-99"}, headers=auth(admin)
    )

    assert response.status_code == 200
    client.cookies.clear()
    client.cookies.set("refresh_token", old_cookie)
    assert client.post("/api/v1/auth/refresh").status_code == 401  # old session ended
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "pw@example.com", "password": DEFAULT_PASSWORD}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "pw@example.com", "password": "Brand-new-99"}
        ).status_code
        == 200
    )


# --------------------------------------------------------------------- deactivate


def test_deactivate_blocks_login_and_existing_tokens(
    client: TestClient, db_session: Session, admin: User
) -> None:
    worker = create_user(db_session, "worker@example.com", roles=(RoleName.STAFF,))
    worker_headers = auth(worker)
    assert client.get("/api/v1/auth/me", headers=worker_headers).status_code == 200

    response = client.post(f"{USERS}/{worker.id}/deactivate", headers=auth(admin))

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert client.get("/api/v1/auth/me", headers=worker_headers).status_code == 401
    login = client.post(
        "/api/v1/auth/login", json={"email": "worker@example.com", "password": DEFAULT_PASSWORD}
    )
    assert login.status_code == 401


def test_deactivate_twice_is_harmless_and_reactivate_works(
    client: TestClient, db_session: Session, admin: User
) -> None:
    worker = create_user(db_session, "again@example.com")

    client.post(f"{USERS}/{worker.id}/deactivate", headers=auth(admin))
    assert client.post(f"{USERS}/{worker.id}/deactivate", headers=auth(admin)).status_code == 200

    response = client.patch(f"{USERS}/{worker.id}", json={"is_active": True}, headers=auth(admin))
    assert response.json()["is_active"] is True


# ------------------------------------------------------------------- safety rules


def test_admin_cannot_deactivate_themselves(client: TestClient, admin: User) -> None:
    response = client.post(f"{USERS}/{admin.id}/deactivate", headers=auth(admin))

    assert response.status_code == 409
    assert response.json() == {"detail": "You cannot deactivate your own account"}


def test_admin_cannot_remove_own_admin_role(client: TestClient, admin: User) -> None:
    response = client.patch(f"{USERS}/{admin.id}", json={"roles": ["staff"]}, headers=auth(admin))

    assert response.status_code == 409


def test_other_admin_can_be_demoted_or_deactivated_when_admins_remain(
    client: TestClient, db_session: Session, admin: User
) -> None:
    second = create_user(db_session, "second@example.com", roles=(RoleName.ADMIN,))
    third = create_user(db_session, "third@example.com", roles=(RoleName.ADMIN,))

    demote = client.patch(f"{USERS}/{second.id}", json={"roles": ["staff"]}, headers=auth(admin))
    deactivate = client.post(f"{USERS}/{third.id}/deactivate", headers=auth(admin))

    assert demote.status_code == 200
    assert deactivate.status_code == 200


def test_last_active_admin_is_protected_at_service_level(db_session: Session) -> None:
    """Defence in depth: even a caller that is not itself an admin (e.g. a script or a
    future background job) can never remove the last active admin."""
    only_admin = create_user(db_session, "only-admin@example.com", roles=(RoleName.ADMIN,))
    create_user(db_session, "old-admin@example.com", roles=(RoleName.ADMIN,), is_active=False)
    system_actor = create_user(db_session, "system@example.com", roles=(RoleName.MANAGER,))
    service = UserService(db_session)

    with pytest.raises(UserRuleViolationError, match="last active admin"):
        service.deactivate_user(only_admin.id, acting_user=system_actor)
    with pytest.raises(UserRuleViolationError, match="last active admin"):
        service.update_user(
            only_admin.id, UserUpdate(roles=[RoleName.STAFF]), acting_user=system_actor
        )
    db_session.refresh(only_admin)
    assert only_admin.is_active is True
    assert only_admin.role_names == {"admin"}


def test_nobody_can_deactivate_themselves_at_service_level(db_session: Session) -> None:
    """Also covers non-admin callers (e.g. future self-service features)."""
    manager = create_user(db_session, "self@example.com", roles=(RoleName.MANAGER,))

    with pytest.raises(UserRuleViolationError, match="your own account"):
        UserService(db_session).deactivate_user(manager.id, acting_user=manager)
    with pytest.raises(UserRuleViolationError, match="your own account"):
        UserService(db_session).update_user(
            manager.id, UserUpdate(is_active=False), acting_user=manager
        )
