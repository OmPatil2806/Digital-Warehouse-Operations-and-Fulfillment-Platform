"""Shared FastAPI dependencies: database session and the authenticated user."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import TokenError, decode_access_token
from app.database.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository

# auto_error=False: we raise our own 401 (FastAPI's default would be 403).
bearer_scheme = HTTPBearer(auto_error=False, description="Access token from POST /auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def unauthorized(detail: str = "Not authenticated") -> HTTPException:
    """401 response that tells the client to send a Bearer token."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Return the active user identified by the `Authorization: Bearer <token>` header."""
    if credentials is None:
        raise unauthorized()
    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise unauthorized(str(exc)) from exc

    user = UserRepository(db).get_by_id(payload.user_id)
    if user is None or not user.is_active:
        # A deleted or deactivated user's access token stops working immediately.
        raise unauthorized("User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
