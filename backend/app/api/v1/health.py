"""Health check endpoint used by the frontend, CI and monitoring."""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Response body of the health endpoint."""

    status: str
    app_name: str
    version: str
    environment: str
    timestamp: datetime


@router.get("/health", response_model=HealthResponse, summary="Service health status")
def health_check() -> HealthResponse:
    """Return basic information showing that the API is running."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        timestamp=datetime.now(UTC),
    )
