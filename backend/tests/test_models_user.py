"""Tests for the User, Role and RefreshToken models."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import RefreshToken, Role, RoleName, User, user_roles


def get_role(db: Session, name: RoleName) -> Role:
    return db.scalars(select(Role).where(Role.name == name)).one()


def make_user(email: str = "alex@example.com", **overrides: object) -> User:
    values: dict[str, object] = {
        "email": email,
        "full_name": "Alex Example",
        "hashed_password": "not-a-real-hash",
    }
    values.update(overrides)
    return User(**values)


def test_migration_seeds_the_four_roles(db_session: Session) -> None:
    names = set(db_session.scalars(select(Role.name)))

    assert names == {role.value for role in RoleName}


def test_new_user_gets_defaults(db_session: Session) -> None:
    user = make_user()
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.id is not None
    assert user.is_active is True
    assert user.last_login_at is None
    assert user.created_at is not None
    assert user.updated_at is not None
    assert user.roles == []


def test_email_must_be_unique(db_session: Session) -> None:
    db_session.add(make_user("dup@example.com"))
    db_session.commit()

    db_session.add(make_user("dup@example.com", full_name="Someone Else"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_user_can_have_multiple_roles(db_session: Session) -> None:
    user = make_user()
    user.roles = [get_role(db_session, RoleName.MANAGER), get_role(db_session, RoleName.STAFF)]
    db_session.add(user)
    db_session.commit()

    loaded = db_session.get(User, user.id)
    assert loaded is not None
    assert loaded.role_names == {"manager", "staff"}
    assert loaded.has_role(RoleName.MANAGER)
    assert loaded.has_role(RoleName.ADMIN, RoleName.STAFF)
    assert not loaded.has_role(RoleName.ADMIN)


def test_same_role_cannot_be_assigned_twice(db_session: Session) -> None:
    user = make_user()
    db_session.add(user)
    db_session.commit()
    admin = get_role(db_session, RoleName.ADMIN)

    db_session.execute(user_roles.insert().values(user_id=user.id, role_id=admin.id))
    with pytest.raises(IntegrityError):
        db_session.execute(user_roles.insert().values(user_id=user.id, role_id=admin.id))
    db_session.rollback()


def test_deleting_user_removes_role_links_and_refresh_tokens(db_session: Session) -> None:
    user = make_user()
    user.roles = [get_role(db_session, RoleName.CUSTOMER)]
    user.refresh_tokens = [
        RefreshToken(token_hash="a" * 64, expires_at=datetime.now(UTC) + timedelta(days=7))
    ]
    db_session.add(user)
    db_session.commit()
    user_id = user.id

    db_session.delete(user)
    db_session.commit()

    links = db_session.scalar(
        select(func.count()).select_from(user_roles).where(user_roles.c.user_id == user_id)
    )
    tokens = db_session.scalar(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user_id)
    )
    assert links == 0
    assert tokens == 0
    # The role itself must still exist.
    assert get_role(db_session, RoleName.CUSTOMER) is not None


def test_refresh_token_hash_must_be_unique(db_session: Session) -> None:
    user = make_user()
    db_session.add(user)
    db_session.commit()
    expires = datetime.now(UTC) + timedelta(days=7)

    db_session.add(RefreshToken(user_id=user.id, token_hash="b" * 64, expires_at=expires))
    db_session.add(RefreshToken(user_id=user.id, token_hash="b" * 64, expires_at=expires))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_refresh_token_requires_existing_user(db_session: Session) -> None:
    db_session.add(
        RefreshToken(
            user_id=999_999, token_hash="c" * 64, expires_at=datetime.now(UTC) + timedelta(days=1)
        )
    )
    with pytest.raises(IntegrityError):  # foreign keys are enforced in SQLite
        db_session.commit()
    db_session.rollback()


def test_refresh_token_revoked_flag(db_session: Session) -> None:
    token = RefreshToken(token_hash="d" * 64, expires_at=datetime.now(UTC))
    assert token.is_revoked is False

    token.revoked_at = datetime.now(UTC)
    assert token.is_revoked is True
