"""Exception handlers that convert errors into JSON responses.

Expected errors (`AppError`) carry a message for the user. Anything else is a bug or an
outage: the details (stack trace, SQL, file paths) go to the server log under a short
reference, and the client only gets a plain message with that reference, so internals
never leak and a support request can still be matched to the log entry.
"""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.exceptions import AppError

logger = get_logger(__name__)

UNEXPECTED_MESSAGE = "Something went wrong on the server. Please try again later"


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # registered for AppError only
        return await unexpected_error_handler(_request, exc)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    reference = uuid4().hex[:12]
    logger.error(
        "Unexpected error %s on %s %s",
        reference,
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"{UNEXPECTED_MESSAGE} (reference {reference})"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
