"""Exception handlers that convert application errors into JSON responses."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions import AppError


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
