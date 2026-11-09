
"""
TeleForward application configuration.

Centralises environment-based settings using Pydantic Settings.
Supports local development through a root-level .env file and
production deployment through Docker environment variables.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve the project root independently of the current working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application-wide configuration."""

    model_config = SettingsConfigDict(
        env_prefix="TELEFORWARD_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    # --------------------------------------------------------
    # Application
    # --------------------------------------------------------

    environment: Literal["development", "testing", "production"] = Field(
        default="production",
        validation_alias="TELEFORWARD_ENV",
    )

    app_name: str = "TeleForward"
    app_version: str = "0.1.0"
    debug: bool = False

    # --------------------------------------------------------
    # HTTP server
    # --------------------------------------------------------

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    # --------------------------------------------------------
    # Storage and database
    # --------------------------------------------------------

    data_dir: Path = Path("./data")
    database_url: str | None = None

    @property
    def effective_database_url(self) -> str:
        """
        Return the configured database URL.

        SQLite is used by default. PostgreSQL can be selected
        by providing TELEFORWARD_DATABASE_URL.
        """
        if self.database_url:
            return self.database_url

        database_path = (
            self.data_dir.expanduser().resolve() / "teleforward.db"
        )

        return f"sqlite+aiosqlite:///{database_path}"

    # --------------------------------------------------------
    # Time and scheduling
    # --------------------------------------------------------

    timezone: str = "Asia/Kolkata"

    # --------------------------------------------------------
    # Logging
    # --------------------------------------------------------

    log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    # --------------------------------------------------------
    # Network and browser security
    # --------------------------------------------------------

    trusted_hosts: list[str] = Field(
        default_factory=lambda: [
            "localhost",
            "127.0.0.1",
        ]
    )

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
        ]
    )

    # --------------------------------------------------------
    # Authentication and session configuration
    # --------------------------------------------------------

    session_cookie_name: str = "teleforward_session"

    session_max_age: int = Field(
        default=86400,
        ge=300,
        le=2592000,
    )

    session_cookie_secure: bool | None = None

    session_cookie_httponly: bool = True

    session_cookie_samesite: Literal[
        "lax",
        "strict",
        "none",
    ] = "lax"

    # --------------------------------------------------------
    # Cryptographic secrets
    # --------------------------------------------------------

    secret_key: SecretStr | None = None

    encryption_key: SecretStr | None = None

    jwt_secret_key: SecretStr | None = None

    # --------------------------------------------------------
    # Derived configuration
    # --------------------------------------------------------

    @property
    def is_production(self) -> bool:
        """Whether the application is running in production."""
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        """Whether the application is running in development."""
        return self.environment == "development"

    @property
    def effective_session_cookie_secure(self) -> bool:
        """
        Determine whether session cookies require HTTPS.

        Production defaults to secure cookies. Development can
        use HTTP without requiring additional configuration.
        """
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure

        return self.is_production


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached application settings instance.

    Caching ensures that application components share the same
    validated configuration throughout the process.
    """
    return Settings()
