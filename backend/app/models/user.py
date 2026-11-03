"""Security tables: users, roles, user-role links and refresh tokens."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column, ForeignKey, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime
from app.models.mixins import IdMixin, TimestampMixin


class RoleName(StrEnum):
    """The four platform roles (see project document, section 2.3)."""

    ADMIN = "admin"
    MANAGER = "manager"
    STAFF = "staff"
    CUSTOMER = "customer"


ROLE_DESCRIPTIONS: dict[RoleName, str] = {
    RoleName.ADMIN: "Manage users, roles, warehouses, settings, audit logs and ML models",
    RoleName.MANAGER: "Monitor KPIs, approve transfers and adjustments, review ML recommendations",
    RoleName.STAFF: "Receive goods, pick and pack orders, scan products and bins",
    RoleName.CUSTOMER: "Create orders, track orders and shipments, view order history",
}


# Many-to-many link between users and roles.
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("assigned_at", UTCDateTime(), server_default=func.now(), nullable=False),
)


class Role(IdMixin, Base):
    """A named permission group, e.g. `admin`."""

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    users: Mapped[list["User"]] = relationship(
        secondary=user_roles, back_populates="roles", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class User(IdMixin, TimestampMixin, Base):
    """A person who can log in to the platform."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    # Roles are almost always needed with the user, so load them in one extra query.
    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin", passive_deletes=True
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def role_names(self) -> set[str]:
        """Names of all roles assigned to the user."""
        return {role.name for role in self.roles}

    def has_role(self, *names: str) -> bool:
        """True if the user has at least one of the given roles."""
        return not self.role_names.isdisjoint(names)

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class RefreshToken(IdMixin, Base):
    """A long-lived refresh token. Only a SHA-256 hash of the token is stored."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))  # long enough for IPv6

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def __repr__(self) -> str:
        return f"<RefreshToken user_id={self.user_id} revoked={self.is_revoked}>"
