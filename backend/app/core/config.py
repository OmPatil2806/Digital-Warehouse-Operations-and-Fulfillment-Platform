"""Application settings loaded from environment variables and the project `.env` file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] is the project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_SECRET_KEY = "change-me-to-a-long-random-secret"
# Environments where the insecure default secret is tolerated.
INSECURE_SECRET_ALLOWED_ENVS = {"development", "test"}
MIN_SECRET_KEY_LENGTH = 32


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

    # ---------- Security ----------
    secret_key: str = DEFAULT_SECRET_KEY
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "digital-warehouse-platform"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=24 * 60)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    # bcrypt cost factor: each +1 doubles hashing time. 12 is a good default;
    # tests use a lower value to stay fast.
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)
    # Send the refresh-token cookie only over HTTPS. Leave unset to decide automatically:
    # off for development/test (plain http://localhost), on everywhere else.
    cookie_secure: bool | None = None

    # Comma-separated list, e.g. "http://localhost:5173,http://127.0.0.1:5173"
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # the shared .env also contains frontend (VITE_) variables
        env_ignore_empty=True,  # `NAME=` (empty) means "use the default"
    )

    @model_validator(mode="after")
    def _check_secret_key(self) -> "Settings":
        """Refuse to start outside development/test with a weak or default secret."""
        if self.app_env in INSECURE_SECRET_ALLOWED_ENVS:
            return self
        if self.secret_key == DEFAULT_SECRET_KEY or len(self.secret_key) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(
                f"SECRET_KEY must be changed and at least {MIN_SECRET_KEY_LENGTH} characters "
                f"long when APP_ENV={self.app_env!r}. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        return self

    @property
    def refresh_cookie_secure(self) -> bool:
        """Whether the refresh-token cookie gets the `Secure` (HTTPS-only) flag."""
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env not in INSECURE_SECRET_ALLOWED_ENVS

    @property
    def is_sqlite(self) -> bool:
        """True when the configured database is SQLite."""
        return self.database_url.startswith("sqlite")

    @property
    def sqlalchemy_database_url(self) -> str:
        """Database URL with relative SQLite paths resolved against the project root.

        This makes `sqlite:///./database/warehouse.db` point to the same file no matter
        whether the app is started from the project root or from `backend/`.
        """
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return self.database_url
        db_path = self.database_url[len(prefix) :]
        if db_path == ":memory:" or Path(db_path).is_absolute():
            return self.database_url
        return f"{prefix}{(PROJECT_ROOT / db_path).resolve().as_posix()}"

    def ensure_sqlite_directory(self) -> None:
        """Create the folder that holds the SQLite file if it does not exist yet."""
        prefix = "sqlite:///"
        url = self.sqlalchemy_database_url
        if url.startswith(prefix) and not url.endswith(":memory:"):
            Path(url[len(prefix) :]).parent.mkdir(parents=True, exist_ok=True)

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read once per process)."""
    return Settings()
