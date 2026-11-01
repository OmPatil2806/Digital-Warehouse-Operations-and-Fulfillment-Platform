"""FastAPI application entry point.

Run locally (from the `backend/` folder):
    uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = get_logger(__name__)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="REST API for warehouse operations, order fulfillment and ML insights.",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=API_V1_PREFIX)

    logger.info(
        "Application started: %s v%s (%s)",
        settings.app_name,
        settings.app_version,
        settings.app_env,
    )
    return app


app = create_app()
