"""Tests for AuthService: login, refresh-token rotation and logout."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token, hash_refresh_token
from app.models.user import RefreshToken, User
from app.services.auth_service import (
    AuthService,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RefreshTokenReuseError,
)
from tests.factories import DEFAULT_PASSWORD, create_user


def active_tokens(db: Session, user: User) -> list[RefreshToken]:
    return list(
        db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            )
        )
    )


# -------------------------------------------------------------------------- login


def test_login_returns_tokens_and_records_last_login(db_session: Session) -> None:
    user = create_user(db_session, "alex@example.com")

    tokens = AuthService(db_session).login(
        "alex@example.com", DEFAULT_PASSWORD, user_agent="pytest", ip_address="127.0.0.1"
    )

    assert decode_access_token(tokens.access_token).user_id == user.id
    assert tokens.expires_in == 30 * 60
    assert tokens.user.id == user.id
    db_session.refresh(user)
    assert user.last_login_at is not None
    assert user.last_login_at.tzinfo is not None  # stored and returned as UTC

    [stored] = active_tokens(db_session, user)
    assert stored.token_hash == hash_refresh_token(tokens.refresh_token)
    assert stored.token_hash != tokens.refresh_token  # raw token is never stored
    assert stored.user_agent == "pytest"
    assert stored.ip_address == "127.0.0.1"


def test_login_email_is_case_insensitive(db_session: Session) -> None:
    create_user(db_session, "case@example.com")

    tokens = AuthService(db_session).login("  CASE@Example.COM ", DEFAULT_PASSWORD)

    assert tokens.access_token


def test_wrong_password_and_unknown_email_give_the_same_error(db_session: Session) -> None:
    create_user(db_session, "known@example.com")
    service = AuthService(db_session)

    with pytest.raises(InvalidCredentialsError) as wrong_password:
        service.login("known@example.com", "Wrong-passw0rd")
    with pytest.raises(InvalidCredentialsError) as unknown_email:
        service.login("nobody@example.com", DEFAULT_PASSWORD)

    assert str(wrong_password.value) == str(unknown_email.value) == "Incorrect email or password"


def test_inactive_user_cannot_log_in(db_session: Session) -> None:
    create_user(db_session, "gone@example.com", is_active=False)

    with pytest.raises(InactiveUserError):
        AuthService(db_session).login("gone@example.com", DEFAULT_PASSWORD)


def test_inactive_user_with_wrong_password_gets_generic_error(db_session: Session) -> None:
    # Account status is only revealed to someone who knows the password.
    create_user(db_session, "gone2@example.com", is_active=False)

    with pytest.raises(InvalidCredentialsError):
        AuthService(db_session).login("gone2@example.com", "Wrong-passw0rd")


def test_each_login_creates_a_separate_session(db_session: Session) -> None:
    user = create_user(db_session, "multi@example.com")
    service = AuthService(db_session)

    service.login("multi@example.com", DEFAULT_PASSWORD)
    service.login("multi@example.com", DEFAULT_PASSWORD)

    assert len(active_tokens(db_session, user)) == 2  # e.g. laptop + phone


# ------------------------------------------------------------------------ refresh


def test_refresh_rotates_the_refresh_token(db_session: Session) -> None:
    user = create_user(db_session, "rotate@example.com")
    service = AuthService(db_session)
    first = service.login("rotate@example.com", DEFAULT_PASSWORD)

    second = service.refresh(first.refresh_token)

    assert second.refresh_token != first.refresh_token
    assert decode_access_token(second.access_token).user_id == user.id
    [active] = active_tokens(db_session, user)
    assert active.token_hash == hash_refresh_token(second.refresh_token)


def test_reusing_a_rotated_token_revokes_all_sessions(db_session: Session) -> None:
    user = create_user(db_session, "stolen@example.com")
    service = AuthService(db_session)
    first = service.login("stolen@example.com", DEFAULT_PASSWORD)
    second = service.refresh(first.refresh_token)
    service.login("stolen@example.com", DEFAULT_PASSWORD)  # another device
    assert len(active_tokens(db_session, user)) == 2

    with pytest.raises(RefreshTokenReuseError):
        service.refresh(first.refresh_token)  # replay of the old token

    assert active_tokens(db_session, user) == []
    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(second.refresh_token)  # the legitimate one is now dead too


def test_unknown_refresh_token_is_rejected(db_session: Session) -> None:
    with pytest.raises(InvalidRefreshTokenError):
        AuthService(db_session).refresh("this-token-was-never-issued")


def test_expired_refresh_token_is_rejected(db_session: Session) -> None:
    user = create_user(db_session, "expired@example.com")
    service = AuthService(db_session)
    tokens = service.login("expired@example.com", DEFAULT_PASSWORD)
    [stored] = active_tokens(db_session, user)
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(tokens.refresh_token)


def test_refresh_fails_and_revokes_sessions_for_deactivated_user(db_session: Session) -> None:
    user = create_user(db_session, "fired@example.com")
    service = AuthService(db_session)
    tokens = service.login("fired@example.com", DEFAULT_PASSWORD)
    user.is_active = False
    db_session.commit()

    with pytest.raises(InactiveUserError):
        service.refresh(tokens.refresh_token)

    assert active_tokens(db_session, user) == []


# ------------------------------------------------------------------------- logout


def test_logout_revokes_the_refresh_token(db_session: Session) -> None:
    user = create_user(db_session, "bye@example.com")
    service = AuthService(db_session)
    tokens = service.login("bye@example.com", DEFAULT_PASSWORD)

    service.logout(tokens.refresh_token)

    assert active_tokens(db_session, user) == []
    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(tokens.refresh_token)


def test_logout_only_ends_that_session(db_session: Session) -> None:
    user = create_user(db_session, "two@example.com")
    service = AuthService(db_session)
    laptop = service.login("two@example.com", DEFAULT_PASSWORD)
    phone = service.login("two@example.com", DEFAULT_PASSWORD)

    service.logout(laptop.refresh_token)

    [remaining] = active_tokens(db_session, user)
    assert remaining.token_hash == hash_refresh_token(phone.refresh_token)


@pytest.mark.parametrize("token", [None, "", "unknown-token"])
def test_logout_is_idempotent_and_never_fails(db_session: Session, token: str | None) -> None:
    AuthService(db_session).logout(token)  # must not raise


def test_logout_everywhere_revokes_all_sessions(db_session: Session) -> None:
    user = create_user(db_session, "all@example.com")
    service = AuthService(db_session)
    service.login("all@example.com", DEFAULT_PASSWORD)
    service.login("all@example.com", DEFAULT_PASSWORD)

    assert service.logout_everywhere(user.id) == 2
    assert active_tokens(db_session, user) == []
