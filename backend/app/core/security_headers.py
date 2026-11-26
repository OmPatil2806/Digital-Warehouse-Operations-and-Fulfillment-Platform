"""HTTP security headers added to every API response.

- `X-Content-Type-Options: nosniff`: browsers must not guess another content type.
- `X-Frame-Options: DENY` and CSP `frame-ancestors 'none'`: the API cannot be framed
  (clickjacking).
- `Content-Security-Policy: default-src 'none'`: JSON responses may load nothing. The
  interactive docs (/docs, /redoc) load their scripts from a CDN, so they are left out.
- `Referrer-Policy: no-referrer`, `Permissions-Policy`: no referrer, no device access.
- `Cache-Control: no-store` on the auth endpoints: tokens are never cached.
- `Strict-Transport-Security` when the site runs on HTTPS (cookies marked Secure).
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
HSTS = "max-age=31536000; includeSubDomains"

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def add_security_headers(app: FastAPI, *, https: bool, auth_prefix: str) -> None:
    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        path = request.url.path
        for name, value in BASE_HEADERS.items():
            response.headers.setdefault(name, value)
        if not path.startswith(DOCS_PATHS):
            response.headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        if path.startswith(auth_prefix):
            response.headers["Cache-Control"] = "no-store"
        if https:
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        return response
