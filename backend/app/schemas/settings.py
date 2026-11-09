
"""
TeleForward application settings schemas.

Defines:
- General application settings.
- Telegram integration settings.
- Forwarding behaviour settings.
- Security settings.
- Storage and logging settings.
- Configuration update requests.
"""

from typing import Literal

from pydantic import Field, SecretStr

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class GeneralSettingsResponse(ResponseSchema):
    """General application preferences."""

    application_name: str = "TeleForward"

    timezone: str = "UTC"

    language: str = "en"

    date_format: str = "YYYY-MM-DD"

    items_per_page: int = Field(
        default=25,
        ge=5,
        le=100,
    )

    theme: Literal["light", "dark", "system"] = "system"


class GeneralSettingsUpdateRequest(RequestSchema):
    """Update general application preferences."""

    application_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    timezone: str | None = Field(
        default=None,
        max_length=100,
    )

    language: str | None = Field(
        default=None,
        max_length=20,
    )

    date_format: str | None = Field(
        default=None,
        max_length=50,
    )

    items_per_page: int | None = Field(
        default=None,
        ge=5,
        le=100,
    )

    theme: Literal["light", "dark", "system"] | None = None


class TelegramSettingsResponse(ResponseSchema):
    """Telegram integration configuration."""

    api_id_configured: bool = False
    api_hash_configured: bool = False

    connection_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
    )

    request_retries: int = Field(
        default=5,
        ge=0,
        le=20,
    )

    auto_reconnect: bool = True


class TelegramSettingsUpdateRequest(RequestSchema):
    """Update Telegram integration settings."""

    api_id: int | None = Field(
        default=None,
        gt=0,
    )

    api_hash: SecretStr | None = None

    connection_timeout: int | None = Field(
        default=None,
        ge=5,
        le=120,
    )

    request_retries: int | None = Field(
        default=None,
        ge=0,
        le=20,
    )

    auto_reconnect: bool | None = None


class ForwardingSettingsResponse(ResponseSchema):
    """Default forwarding behaviour configuration."""

    default_mode: Literal["forward", "copy"] = "forward"

    preserve_grouped_media: bool = True

    sync_edits: bool = False
    sync_deletions: bool = False

    prevent_duplicates: bool = True

    retry_failed_deliveries: bool = True

    max_retry_attempts: int = Field(
        default=5,
        ge=0,
        le=50,
    )

    retry_delay_seconds: int = Field(
        default=30,
        ge=1,
        le=86400,
    )


class ForwardingSettingsUpdateRequest(RequestSchema):
    """Update default forwarding behaviour."""

    default_mode: Literal["forward", "copy"] | None = None

    preserve_grouped_media: bool | None = None

    sync_edits: bool | None = None
    sync_deletions: bool | None = None

    prevent_duplicates: bool | None = None

    retry_failed_deliveries: bool | None = None

    max_retry_attempts: int | None = Field(
        default=None,
        ge=0,
        le=50,
    )

    retry_delay_seconds: int | None = Field(
        default=None,
        ge=1,
        le=86400,
    )


class SecuritySettingsResponse(ResponseSchema):
    """Application security preferences."""

    session_timeout_minutes: int = Field(
        default=60,
        ge=5,
        le=10080,
    )

    max_login_attempts: int = Field(
        default=5,
        ge=1,
        le=50,
    )

    login_lockout_minutes: int = Field(
        default=15,
        ge=1,
        le=1440,
    )

    require_secure_cookies: bool = True

    audit_logging_enabled: bool = True


class SecuritySettingsUpdateRequest(RequestSchema):
    """Update configurable security preferences."""

    session_timeout_minutes: int | None = Field(
        default=None,
        ge=5,
        le=10080,
    )

    max_login_attempts: int | None = Field(
        default=None,
        ge=1,
        le=50,
    )

    login_lockout_minutes: int | None = Field(
        default=None,
        ge=1,
        le=1440,
    )

    require_secure_cookies: bool | None = None

    audit_logging_enabled: bool | None = None


class StorageSettingsResponse(ResponseSchema):
    """Application storage configuration."""

    storage_backend: Literal["local"] = "local"

    media_storage_enabled: bool = True

    maximum_upload_size_mb: int = Field(
        default=2048,
        ge=1,
        le=102400,
    )

    backup_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
    )


class StorageSettingsUpdateRequest(RequestSchema):
    """Update storage preferences."""

    media_storage_enabled: bool | None = None

    maximum_upload_size_mb: int | None = Field(
        default=None,
        ge=1,
        le=102400,
    )

    backup_retention_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
    )


class LoggingSettingsResponse(ResponseSchema):
    """Application logging configuration."""

    log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    retention_days: int = Field(
        default=14,
        ge=1,
        le=3650,
    )


class LoggingSettingsUpdateRequest(RequestSchema):
    """Update logging preferences."""

    log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] | None = None

    retention_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
    )


class ApplicationSettingsResponse(ResponseSchema):
    """Aggregated application configuration."""

    general: GeneralSettingsResponse
    telegram: TelegramSettingsResponse
    forwarding: ForwardingSettingsResponse
    security: SecuritySettingsResponse
    storage: StorageSettingsResponse
    logging: LoggingSettingsResponse
