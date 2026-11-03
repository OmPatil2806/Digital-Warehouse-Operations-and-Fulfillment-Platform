"""Request and response schemas for users."""

from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

from app.core.security import BCRYPT_MAX_PASSWORD_BYTES
from app.models.user import RoleName

PASSWORD_MIN_LENGTH = 8


def normalize_email(value: str) -> str:
    """Emails are case-insensitive: store and compare them in lower case."""
    return value.strip().lower()


def validate_password_strength(value: str) -> str:
    """Password policy: 8+ characters, at most 72 bytes, at least one letter and one digit."""
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long")
    if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes long")
    if not any(char.isalpha() for char in value):
        raise ValueError("Password must contain at least one letter")
    if not any(char.isdigit() for char in value):
        raise ValueError("Password must contain at least one digit")
    return value


Email = Annotated[EmailStr, AfterValidator(normalize_email)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
NewPassword = Annotated[str, AfterValidator(validate_password_strength)]


class UserCreate(BaseModel):
    """Data an administrator provides to create a user."""

    email: Email
    full_name: FullName
    password: NewPassword
    roles: list[RoleName] = Field(default_factory=lambda: [RoleName.CUSTOMER], min_length=1)

    @field_validator("roles")
    @classmethod
    def _unique_roles(cls, roles: list[RoleName]) -> list[RoleName]:
        return list(dict.fromkeys(roles))  # drop duplicates, keep order


class UserUpdate(BaseModel):
    """Partial update; only the fields that are sent are changed."""

    email: Email | None = None
    full_name: FullName | None = None
    password: NewPassword | None = None
    roles: list[RoleName] | None = Field(default=None, min_length=1)
    is_active: bool | None = None

    @field_validator("roles")
    @classmethod
    def _unique_roles(cls, roles: list[RoleName] | None) -> list[RoleName] | None:
        return None if roles is None else list(dict.fromkeys(roles))


class UserResponse(BaseModel):
    """A user as returned by the API. Never contains the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    is_active: bool
    roles: list[str]
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator("roles", mode="before")
    @classmethod
    def _role_names(cls, roles: list[object]) -> list[str]:
        """Accept Role objects (from the ORM) or plain names, return sorted names."""
        return sorted(getattr(role, "name", role) for role in roles)  # type: ignore[misc]
