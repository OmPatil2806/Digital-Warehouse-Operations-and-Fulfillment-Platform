"""Application settings loaded from environment variables and the project `.env` file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] is the project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Typed application settings.

    Values are read (highest priority first) from real environment variables,
    then from the `.env` file in the project root, then from the defaults below.
    """

    app_name: str = "Digital Warehouse Operations and Fulfillment Platform"
    app_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./database/warehouse.db"

    secret_key: str = "change-me-to-a-long-random-secret"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Comma-separated list, e.g. "http://localhost:5173,http://127.0.0.1:5173"
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # the shared .env also contains frontend (VITE_) variables
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read once per process)."""
    return Settings()
