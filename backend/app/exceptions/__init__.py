"""Application errors raised by the service layer.

Services raise these instead of HTTP exceptions, so business logic stays independent
of FastAPI. `app.exceptions.handlers` turns them into JSON responses:
`{"detail": "<message>"}` with the matching HTTP status code.
"""

from http import HTTPStatus


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    status_code: int = HTTPStatus.BAD_REQUEST
    message: str = "Request could not be processed"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.message
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    message = "Resource not found"


class ConflictError(AppError):
    """The request conflicts with existing data or a business rule."""

    status_code = HTTPStatus.CONFLICT
    message = "Request conflicts with the current state"
