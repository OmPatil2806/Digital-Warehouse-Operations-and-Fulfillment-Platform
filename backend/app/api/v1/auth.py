"""Authentication endpoints: login, refresh, logout and current user.

Token handling:
- The short-lived access token is returned in the JSON body. The frontend keeps it in
  memory and sends it as `Authorization: Bearer <token>`.
- The long-lived refresh token is set as an httpOnly cookie that JavaScript cannot
  read. It is only sent to the /api/v1/auth endpoints.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services.auth_service import AuthError, AuthService, AuthTokens

router = APIRouter(prefix="/auth", tags=["Authentication"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"  # the cookie is never sent to other endpoints

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)]

AUTH_ERROR_RESPONSES: dict[int | str, dict[str, str]] = {
    401: {"description": "Invalid credentials or token"},
}


def _client_info(request: Request) -> dict[str, str | None]:
    return {
        "user_agent": request.headers.get("user-agent"),
        "ip_address": request.client.host if request.client else None,
    }


def _set_refresh_cookie(response: Response, tokens: AuthTokens) -> None:
    max_age = int((tokens.refresh_expires_at - datetime.now(UTC)).total_seconds())
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=tokens.refresh_token,
        max_age=max_age,
        path=REFRESH_COOKIE_PATH,
        httponly=True,  # not readable from JavaScript (protects against XSS theft)
        secure=get_settings().refresh_cookie_secure,  # HTTPS-only outside development
        samesite="lax",  # not sent on cross-site POSTs (protects against CSRF)
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )


def _token_response(tokens: AuthTokens) -> TokenResponse:
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


def _auth_error_response(error: AuthError, *, clear_cookie: bool = False) -> JSONResponse:
    response = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": str(error)},
        headers={"WWW-Authenticate": "Bearer"},
    )
    if clear_cookie:
        _clear_refresh_cookie(response)
    return response


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with email and password",
    responses=AUTH_ERROR_RESPONSES,
)
def login(
    credentials: LoginRequest, request: Request, response: Response, db: DbSession
) -> TokenResponse | JSONResponse:
    """Return an access token and set the refresh-token cookie."""
    try:
        tokens = AuthService(db).login(
            credentials.normalized_email(), credentials.password, **_client_info(request)
        )
    except AuthError as error:
        return _auth_error_response(error)
    _set_refresh_cookie(response, tokens)
    return _token_response(tokens)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Get a new access token using the refresh-token cookie",
    responses=AUTH_ERROR_RESPONSES,
)
def refresh(
    request: Request,
    response: Response,
    db: DbSession,
    refresh_token: RefreshCookie = None,
) -> TokenResponse | JSONResponse:
    """Rotate the refresh token and return a new access token."""
    if not refresh_token:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Refresh token missing"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        tokens = AuthService(db).refresh(refresh_token, **_client_info(request))
    except AuthError as error:
        return _auth_error_response(error, clear_cookie=True)
    _set_refresh_cookie(response, tokens)
    return _token_response(tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out (revoke the refresh token of this browser)",
)
def logout(db: DbSession, refresh_token: RefreshCookie = None) -> Response:
    """Revoke the current refresh token and clear the cookie. Always succeeds."""
    AuthService(db).logout(refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the logged-in user",
    responses=AUTH_ERROR_RESPONSES,
)
def me(user: CurrentUser) -> UserResponse:
    """Return the user that the access token belongs to."""
    return UserResponse.model_validate(user)
