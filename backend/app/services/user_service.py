"""User management business logic (used by admins and the create_admin script).

Safety rules that prevent locking everyone out of the platform:
- An admin cannot deactivate themselves or remove their own admin role.
- The last active admin cannot be deactivated or lose the admin role.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import hash_password
from app.exceptions import ConflictError, NotFoundError
from app.models.user import RoleName, User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.services.auth_service import AuthService

logger = get_logger(__name__)


class UserNotFoundError(NotFoundError):
    message = "User not found"


class EmailAlreadyExistsError(ConflictError):
    message = "A user with this email already exists"


class UserRuleViolationError(ConflictError):
    """A change was refused because it would break a safety rule."""


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    # ------------------------------------------------------------------- read
    def list_users(self, *, offset: int = 0, limit: int = 50) -> tuple[Sequence[User], int]:
        return self.users.list_users(offset=offset, limit=limit), self.users.count()

    def get_user(self, user_id: int) -> User:
        user = self.users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        return user

    # ----------------------------------------------------------------- create
    def create_user(self, data: UserCreate) -> User:
        if self.users.email_exists(data.email):
            raise EmailAlreadyExistsError()
        user = User(
            email=data.email,
            full_name=data.full_name,
            hashed_password=hash_password(data.password),
        )
        user.roles = self.users.get_roles_by_names(data.roles)
        self.users.add(user)
        self._commit_or_conflict()
        logger.info("Created user %s with roles %s", user.id, sorted(user.role_names))
        return user

    # ----------------------------------------------------------------- update
    def update_user(self, user_id: int, data: UserUpdate, *, acting_user: User) -> User:
        """Apply a partial update. Only fields that were sent are changed."""
        user = self.get_user(user_id)
        changes = data.model_dump(exclude_unset=True)

        if "email" in changes and changes["email"] is not None:
            if self.users.email_exists(changes["email"], exclude_user_id=user.id):
                raise EmailAlreadyExistsError()
            user.email = changes["email"]

        if changes.get("full_name") is not None:
            user.full_name = changes["full_name"]

        if changes.get("roles") is not None:
            new_roles = {str(role) for role in changes["roles"]}
            if RoleName.ADMIN in user.role_names and RoleName.ADMIN not in new_roles:
                self._ensure_admin_can_be_removed(user, acting_user, "remove the admin role from")
            user.roles = self.users.get_roles_by_names(new_roles)

        if changes.get("is_active") is not None and changes["is_active"] != user.is_active:
            if changes["is_active"]:
                user.is_active = True
            else:
                self._deactivate(user, acting_user)

        password_changed = changes.get("password") is not None
        if password_changed:
            user.hashed_password = hash_password(changes["password"])

        self._commit_or_conflict()
        if password_changed:
            # Sessions started with the old password must not stay valid.
            AuthService(self.db).logout_everywhere(user.id)
        logger.info("User %s updated by %s: %s", user.id, acting_user.id, sorted(changes))
        return user

    def deactivate_user(self, user_id: int, *, acting_user: User) -> User:
        user = self.get_user(user_id)
        if user.is_active:
            self._deactivate(user, acting_user)
            self._commit_or_conflict()
            logger.info("User %s deactivated by %s", user.id, acting_user.id)
        return user

    # ---------------------------------------------------------------- helpers
    def _deactivate(self, user: User, acting_user: User) -> None:
        if user.id == acting_user.id:
            raise UserRuleViolationError("You cannot deactivate your own account")
        if RoleName.ADMIN in user.role_names:
            self._ensure_admin_can_be_removed(user, acting_user, "deactivate")
        user.is_active = False
        # Log the user out everywhere; their access token stops working on its next use
        # because get_current_user checks `is_active`.
        self.users.revoke_all_refresh_tokens(user.id, revoked_at=datetime.now(UTC))

    def _ensure_admin_can_be_removed(self, user: User, acting_user: User, action: str) -> None:
        if user.id == acting_user.id:
            raise UserRuleViolationError(f"You cannot {action} your own account")
        if user.is_active and self.users.count_active_with_role(RoleName.ADMIN) <= 1:
            raise UserRuleViolationError(f"Cannot {action} the last active admin")

    def _commit_or_conflict(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:  # e.g. two requests created the same email at once
            self.db.rollback()
            raise EmailAlreadyExistsError() from exc
