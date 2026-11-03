"""Helpers that create test data."""

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import RoleName, User
from app.repositories.user_repository import UserRepository

DEFAULT_PASSWORD = "Passw0rd-123"


def create_user(
    db: Session,
    email: str = "user@example.com",
    *,
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Test User",
    roles: tuple[RoleName, ...] = (RoleName.CUSTOMER,),
    is_active: bool = True,
) -> User:
    """Insert a user with the given roles and commit."""
    repo = UserRepository(db)
    user = User(
        email=email.lower(),
        full_name=full_name,
        hashed_password=hash_password(password),
        is_active=is_active,
    )
    user.roles = repo.get_roles_by_names(roles)
    repo.add(user)
    db.commit()
    return user
