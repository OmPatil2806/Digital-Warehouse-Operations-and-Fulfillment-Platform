"""ORM models.

Every model module must be imported here so that `Base.metadata` knows all tables
(Alembic autogenerate and the test database rely on this).
"""

from app.models.user import ROLE_DESCRIPTIONS, RefreshToken, Role, RoleName, User, user_roles

__all__ = ["ROLE_DESCRIPTIONS", "RefreshToken", "Role", "RoleName", "User", "user_roles"]
