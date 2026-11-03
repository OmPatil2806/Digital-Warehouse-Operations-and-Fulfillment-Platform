"""Password hashing, JWT access tokens and opaque refresh tokens.

Design:
- Passwords are hashed with bcrypt (via pwdlib). Only the hash is ever stored.
- Access tokens are short-lived signed JWTs sent with every API request.
- Refresh tokens are long, random, opaque strings (not JWTs). They are only ever
  checked against the database, where just their SHA-256 hash is stored, so a
  leaked database does not reveal usable refresh tokens.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import get_settings

ACCESS_TOKEN_TYPE = "access"
BCRYPT_MAX_PASSWORD_BYTES = 72  # bcrypt ignores (bcrypt 5 rejects) anything longer
REFRESH_TOKEN_BYTES = 48  # 48 random bytes -> 64-character URL-safe string

_REQUIRED_ACCESS_CLAIMS = ["sub", "type", "iat", "exp", "iss", "jti"]


# --------------------------------------------------------------------------- errors
class PasswordTooLongError(ValueError):
    """Raised when a password exceeds bcrypt's 72-byte limit."""


class TokenError(Exception):
    """Raised when an access token is missing, invalid, expired or of the wrong type."""


# ------------------------------------------------------------------------ passwords
@lru_cache
def _password_hasher() -> PasswordHash:
    return PasswordHash((BcryptHasher(rounds=get_settings().bcrypt_rounds),))


def _check_password_length(password: str) -> None:
    if len(password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(
            f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes long"
        )


def hash_password(password: str) -> str:
    """Return a salted bcrypt hash of the password."""
    _check_password_length(password)
    return _password_hasher().hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Check a plain password against a stored hash. Never raises for bad input."""
    if len(password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        return False
    try:
        return _password_hasher().verify(password, hashed_password)
    except (PwdlibError, ValueError):  # unknown or malformed hash in the database
        return False


@lru_cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def simulate_password_check() -> None:
    """Spend the same time as a real check, for logins with an unknown email.

    Without this, "unknown email" would answer faster than "wrong password",
    letting an attacker discover which email addresses are registered.
    """
    verify_password("not-the-password", _dummy_hash())


# -------------------------------------------------------------------- access tokens
@dataclass(frozen=True)
class AccessTokenPayload:
    """Verified contents of an access token."""

    user_id: int
    jti: str
    issued_at: datetime
    expires_at: datetime


def create_access_token(
    user_id: int,
    *,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token for the given user."""
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    claims: dict[str, Any] = {
        **(extra_claims or {}),
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": expires_at,
        "iss": settings.jwt_issuer,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> AccessTokenPayload:
    """Verify an access token and return its payload.

    Raises:
        TokenError: if the token is malformed, has a bad signature, is expired,
            comes from another issuer or is not an access token.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],  # never trust the token's own "alg"
            issuer=settings.jwt_issuer,
            options={"require": _REQUIRED_ACCESS_CLAIMS},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc

    if claims.get("type") != ACCESS_TOKEN_TYPE:
        raise TokenError("Invalid token type")
    try:
        user_id = int(claims["sub"])
    except (TypeError, ValueError) as exc:
        raise TokenError("Invalid token subject") from exc

    return AccessTokenPayload(
        user_id=user_id,
        jti=str(claims["jti"]),
        issued_at=datetime.fromtimestamp(claims["iat"], UTC),
        expires_at=datetime.fromtimestamp(claims["exp"], UTC),
    )


# ------------------------------------------------------------------- refresh tokens
@dataclass(frozen=True)
class NewRefreshToken:
    """A freshly generated refresh token.

    `token` is given to the client (once); only `token_hash` is saved in the database.
    """

    token: str
    token_hash: str
    expires_at: datetime


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex digest (64 chars) used to store and look up refresh tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_refresh_token(*, expires_delta: timedelta | None = None) -> NewRefreshToken:
    """Create a new random refresh token and its database hash."""
    settings = get_settings()
    token = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    expires_at = datetime.now(UTC) + (
        expires_delta or timedelta(days=settings.refresh_token_expire_days)
    )
    return NewRefreshToken(token=token, token_hash=hash_refresh_token(token), expires_at=expires_at)
