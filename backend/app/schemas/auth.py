"""Request and response schemas for authentication."""

from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import normalize_email

# Login accepts any non-empty password up to a generous limit. The strength policy only
# applies when a password is set, so old passwords keep working if the policy changes.
LoginPassword = Annotated[str, Field(min_length=1, max_length=128)]


class LoginRequest(BaseModel):
    """Credentials sent to POST /auth/login."""

    email: EmailStr
    password: LoginPassword

    def normalized_email(self) -> str:
        return normalize_email(self.email)


class TokenResponse(BaseModel):
    """Access token returned after login or refresh.

    The refresh token is NOT part of the body: it is set as an httpOnly cookie.
    """

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
