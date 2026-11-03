"""Authentication business logic: login, refresh-token rotation and logout.

Refresh-token rotation:
- Every successful refresh revokes the presented refresh token and issues a new one.
- If an already-revoked token is presented again, it has probably been stolen and
  replayed. All refresh tokens of that user are then revoked ("log out everywhere"),
  and the user has to log in again.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    simulate_password_check,
    verify_password,
)
from app.models.user import RefreshToken, User
from app.repositories.user_repository import UserRepository

logger = get_logger(__name__)

USER_AGENT_MAX_LENGTH = 255
IP_ADDRESS_MAX_LENGTH = 45


# --------------------------------------------------------------------------- errors
class AuthError(Exception):
    """Base class for authentication failures (mapped to HTTP 401 by the API)."""

    message = "Authentication failed"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)


class InvalidCredentialsError(AuthError):
    # The same message for "unknown email" and "wrong password", on purpose.
    message = "Incorrect email or password"


class InactiveUserError(AuthError):
    message = "This account has been deactivated"


class InvalidRefreshTokenError(AuthError):
    message = "Invalid or expired refresh token"


class RefreshTokenReuseError(InvalidRefreshTokenError):
    """A revoked refresh token was used again; all sessions of the user were revoked."""


# --------------------------------------------------------------------------- result
@dataclass(frozen=True)
class AuthTokens:
    """Tokens issued after login or refresh."""

    user: User
    access_token: str
    expires_in: int  # access-token lifetime in seconds
    refresh_token: str  # raw value: send to the client once, never store it
    refresh_expires_at: datetime


# -------------------------------------------------------------------------- service
class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    def authenticate(self, email: str, password: str) -> User:
        """Return the user if the credentials are valid, otherwise raise."""
        user = self.users.get_by_email(email)
        if user is None:
            simulate_password_check()  # same timing as a wrong password
            raise InvalidCredentialsError()
        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()
        if not user.is_active:
            raise InactiveUserError()
        return user

    def login(
        self,
        email: str,
        password: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> AuthTokens:
        """Verify credentials, record the login and issue new tokens."""
        user = self.authenticate(email, password)
        user.last_login_at = datetime.now(UTC)
        tokens = self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)
        self.db.commit()
        logger.info("User %s logged in", user.id)
        return tokens

    def refresh(
        self,
        refresh_token: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> AuthTokens:
        """Exchange a valid refresh token for new tokens (rotation)."""
        now = datetime.now(UTC)
        stored = self.users.get_refresh_token_by_hash(hash_refresh_token(refresh_token))
        if stored is None:
            raise InvalidRefreshTokenError()

        if stored.is_revoked:
            revoked = self.users.revoke_all_refresh_tokens(stored.user_id, revoked_at=now)
            self.db.commit()
            logger.warning(
                "Refresh token reuse detected for user %s; revoked %s active session(s)",
                stored.user_id,
                revoked,
            )
            raise RefreshTokenReuseError()

        if stored.expires_at <= now:
            raise InvalidRefreshTokenError()

        user = stored.user
        if not user.is_active:
            self.users.revoke_all_refresh_tokens(user.id, revoked_at=now)
            self.db.commit()
            raise InactiveUserError()

        stored.revoked_at = now
        tokens = self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)
        self.db.commit()
        return tokens

    def logout(self, refresh_token: str | None) -> None:
        """Revoke the given refresh token. Always succeeds (idempotent)."""
        if not refresh_token:
            return
        stored = self.users.get_refresh_token_by_hash(hash_refresh_token(refresh_token))
        if stored is not None and not stored.is_revoked:
            stored.revoked_at = datetime.now(UTC)
            self.db.commit()
            logger.info("User %s logged out", stored.user_id)

    def logout_everywhere(self, user_id: int) -> int:
        """Revoke all refresh tokens of a user (e.g. after a password change)."""
        revoked = self.users.revoke_all_refresh_tokens(user_id, revoked_at=datetime.now(UTC))
        self.db.commit()
        return revoked

    # ------------------------------------------------------------------ helpers
    def _issue_tokens(
        self, user: User, *, user_agent: str | None, ip_address: str | None
    ) -> AuthTokens:
        settings = get_settings()
        new_refresh = generate_refresh_token()
        self.users.add_refresh_token(
            RefreshToken(
                user_id=user.id,
                token_hash=new_refresh.token_hash,
                expires_at=new_refresh.expires_at,
                user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
                ip_address=ip_address[:IP_ADDRESS_MAX_LENGTH] if ip_address else None,
            )
        )
        return AuthTokens(
            user=user,
            access_token=create_access_token(user.id),
            expires_in=settings.access_token_expire_minutes * 60,
            refresh_token=new_refresh.token,
            refresh_expires_at=new_refresh.expires_at,
        )
