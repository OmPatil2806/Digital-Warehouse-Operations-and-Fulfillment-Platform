"""Health check endpoint used by the frontend, CI and monitoring."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import check_database_connection, get_db

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Response body of the health endpoint."""

    status: str  # "ok" when every dependency works, otherwise "degraded"
    app_name: str
    version: str
    environment: str
    database: str  # "ok" or "unavailable"
    timestamp: datetime


@router.get("/health", response_model=HealthResponse, summary="Service health status")
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Return basic information showing that the API and database are reachable."""
    settings = get_settings()
    database_ok = check_database_connection(db)
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        database="ok" if database_ok else "unavailable",
        timestamp=datetime.now(UTC),
    )
