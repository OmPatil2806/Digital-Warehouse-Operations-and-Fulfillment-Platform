"""Database access for users, roles and refresh tokens.

Repositories only read and write rows; they never commit. Committing (and all
business rules) is the job of the service layer.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.user import RefreshToken, Role, RoleName, User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------------------------------------------------------- users
    def get_by_id(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        """Case-insensitive lookup (emails are stored in lower case)."""
        return self.db.scalars(select(User).where(User.email == email.strip().lower())).first()

    def email_exists(self, email: str, *, exclude_user_id: int | None = None) -> bool:
        query = select(User.id).where(User.email == email.strip().lower())
        if exclude_user_id is not None:
            query = query.where(User.id != exclude_user_id)
        return self.db.scalars(query).first() is not None

    def _filtered(self, *, q: str | None, role: str | None, is_active: bool | None) -> Select:
        query = select(User)
        if q:
            # "%" and "_" typed by the user are literal characters, not wildcards
            text = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{text}%"
            query = query.where(
                or_(
                    func.lower(User.email).like(pattern, escape="\\"),
                    func.lower(User.full_name).like(pattern, escape="\\"),
                )
            )
        if role:
            query = query.where(User.roles.any(Role.name == role))
        if is_active is not None:
            query = query.where(User.is_active.is_(is_active))
        return query

    def list_users(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        q: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> Sequence[User]:
        query = self._filtered(q=q, role=role, is_active=is_active).order_by(User.id)
        return self.db.scalars(query.offset(offset).limit(limit)).all()

    def count_filtered(
        self, *, q: str | None = None, role: str | None = None, is_active: bool | None = None
    ) -> int:
        query = self._filtered(q=q, role=role, is_active=is_active)
        return self.db.scalar(select(func.count()).select_from(query.subquery())) or 0

    def count(self) -> int:
        return self.db.scalar(select(func.count()).select_from(User)) or 0

    def add(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()  # assigns user.id without committing
        return user

    def count_active_with_role(self, role: RoleName) -> int:
        query = (
            select(func.count(func.distinct(User.id)))
            .join(User.roles)
            .where(Role.name == role, User.is_active.is_(True))
        )
        return self.db.scalar(query) or 0

    # ---------------------------------------------------------------- roles
    def get_roles_by_names(self, names: Iterable[str]) -> list[Role]:
        """Return Role rows for the given names; raises if any name is unknown."""
        wanted = set(names)
        roles = list(self.db.scalars(select(Role).where(Role.name.in_(wanted))))
        missing = wanted - {role.name for role in roles}
        if missing:
            raise LookupError(f"Unknown role(s): {', '.join(sorted(missing))}")
        return sorted(roles, key=lambda role: role.name)

    # -------------------------------------------------------- refresh tokens
    def add_refresh_token(self, token: RefreshToken) -> RefreshToken:
        self.db.add(token)
        self.db.flush()
        return token

    def get_refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        return self.db.scalars(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).first()

    def revoke_all_refresh_tokens(self, user_id: int, *, revoked_at: datetime) -> int:
        """Revoke every still-active refresh token of a user. Returns how many."""
        result = self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount or 0
