"""Tests for user schemas (validation) and UserRepository."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.user import RoleName, User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from tests.factories import create_user

VALID = {"email": "New.User@Example.com", "full_name": "  New User  ", "password": "Secur3-pass"}

# ------------------------------------------------------------------------ schemas


def test_user_create_normalizes_input_and_defaults_to_customer() -> None:
    data = UserCreate(**VALID)

    assert data.email == "new.user@example.com"
    assert data.full_name == "New User"
    assert data.roles == [RoleName.CUSTOMER]


def test_user_create_removes_duplicate_roles() -> None:
    data = UserCreate(**VALID, roles=["staff", "manager", "staff"])

    assert data.roles == [RoleName.STAFF, RoleName.MANAGER]


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("Sh0rt", "at least 8 characters"),
        ("onlyletters", "at least one digit"),
        ("12345678", "at least one letter"),
        ("a1" + "x" * 71, "at most 72 bytes"),
    ],
)
def test_weak_passwords_are_rejected(password: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        UserCreate(**{**VALID, "password": password})


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"full_name": "   "},
        {"full_name": "x" * 121},
        {"roles": []},
        {"roles": ["superuser"]},
    ],
)
def test_invalid_user_create_input_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        UserCreate(**{**VALID, **overrides})


def test_user_update_only_contains_sent_fields() -> None:
    update = UserUpdate(full_name="Renamed")

    assert update.model_dump(exclude_unset=True) == {"full_name": "Renamed"}


def test_login_request_normalizes_email_and_limits_password() -> None:
    assert LoginRequest(email="ME@Example.com", password="x").normalized_email() == (
        "me@example.com"
    )
    with pytest.raises(ValidationError):
        LoginRequest(email="me@example.com", password="")
    with pytest.raises(ValidationError):
        LoginRequest(email="me@example.com", password="x" * 129)


def test_user_response_has_role_names_and_no_password(db_session: Session) -> None:
    user = create_user(db_session, "resp@example.com", roles=(RoleName.STAFF, RoleName.MANAGER))

    body = UserResponse.model_validate(user).model_dump()

    assert body["roles"] == ["manager", "staff"]
    assert "hashed_password" not in body
    assert "password" not in body
    assert body["created_at"].tzinfo is not None


# --------------------------------------------------------------------- repository


def test_get_by_email_is_case_insensitive(db_session: Session) -> None:
    user = create_user(db_session, "lookup@example.com")
    repo = UserRepository(db_session)

    assert repo.get_by_email("LOOKUP@example.com") == user
    assert repo.get_by_email("missing@example.com") is None


def test_email_exists_can_exclude_a_user(db_session: Session) -> None:
    user = create_user(db_session, "taken@example.com")
    repo = UserRepository(db_session)

    assert repo.email_exists("taken@example.com") is True
    assert repo.email_exists("taken@example.com", exclude_user_id=user.id) is False


def test_list_and_count_with_pagination(db_session: Session) -> None:
    for number in range(5):
        create_user(db_session, f"page{number}@example.com")
    repo = UserRepository(db_session)

    assert repo.count() == 5
    assert [u.email for u in repo.list_users(offset=1, limit=2)] == [
        "page1@example.com",
        "page2@example.com",
    ]


def test_get_roles_by_names_rejects_unknown_roles(db_session: Session) -> None:
    repo = UserRepository(db_session)

    assert [r.name for r in repo.get_roles_by_names(["staff", "admin"])] == ["admin", "staff"]
    with pytest.raises(LookupError, match="superuser"):
        repo.get_roles_by_names(["admin", "superuser"])


def test_count_active_with_role(db_session: Session) -> None:
    create_user(db_session, "a1@example.com", roles=(RoleName.ADMIN,))
    create_user(db_session, "a2@example.com", roles=(RoleName.ADMIN, RoleName.MANAGER))
    create_user(db_session, "a3@example.com", roles=(RoleName.ADMIN,), is_active=False)
    create_user(db_session, "m1@example.com", roles=(RoleName.MANAGER,))

    assert UserRepository(db_session).count_active_with_role(RoleName.ADMIN) == 2


def test_utc_datetime_column_rejects_naive_datetimes(db_session: Session) -> None:
    user = create_user(db_session, "naive@example.com")
    user.last_login_at = datetime(2026, 1, 1)  # no timezone

    with pytest.raises(Exception, match="timezone-aware"):
        db_session.commit()
    db_session.rollback()

    user = db_session.get(User, user.id)
    assert user is not None
    user.last_login_at = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.commit()
    db_session.refresh(user)
    assert user.last_login_at == datetime(2026, 1, 1, tzinfo=UTC)
