
"""
TeleForward system schemas.

Defines:
- Application runtime information.
- System health status.
- Storage utilization.
- Database diagnostics.
- Application configuration summaries.
- System resource information.

Never expose secrets, environment variables, internal credentials,
or sensitive filesystem paths through these schemas.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import ResponseSchema


class SystemHealthStatusSchema(StrEnum):
    """Overall system health states."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    STOPPING = "stopping"


class SystemComponentStatusSchema(StrEnum):
    """Individual system component health states."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class DatabaseTypeSchema(StrEnum):
    """Supported database engines."""

    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"


class SystemVersionResponse(ResponseSchema):
    """Application version information."""

    application_name: str = "TeleForward"

    version: str

    api_version: str

    environment: str

    python_version: str

    build_date: datetime | None = None


class SystemComponentHealthResponse(ResponseSchema):
    """Health information for one application component."""

    component: str

    status: SystemComponentStatusSchema

    message: str | None = Field(
        default=None,
        max_length=1000,
    )

    checked_at: datetime

    response_time_ms: float | None = Field(
        default=None,
        ge=0,
    )


class SystemHealthResponse(ResponseSchema):
    """Aggregated application health information."""

    status: SystemHealthStatusSchema

    application: SystemComponentHealthResponse

    database: SystemComponentHealthResponse

    telegram: SystemComponentHealthResponse

    scheduler: SystemComponentHealthResponse

    storage: SystemComponentHealthResponse

    uptime_seconds: float = Field(
        ge=0,
    )

    checked_at: datetime


class SystemStorageResponse(ResponseSchema):
    """Persistent storage utilization."""

    total_bytes: int | None = Field(
        default=None,
        ge=0,
    )

    used_bytes: int = Field(
        ge=0,
    )

    free_bytes: int | None = Field(
        default=None,
        ge=0,
    )

    database_bytes: int = Field(
        default=0,
        ge=0,
    )

    telegram_sessions_bytes: int = Field(
        default=0,
        ge=0,
    )

    media_bytes: int = Field(
        default=0,
        ge=0,
    )

    backup_bytes: int = Field(
        default=0,
        ge=0,
    )

    measured_at: datetime


class SystemDatabaseResponse(ResponseSchema):
    """Database configuration and operational information."""

    database_type: DatabaseTypeSchema

    connected: bool

    schema_version: str | None = None

    pool_size: int | None = Field(
        default=None,
        ge=0,
    )

    checked_out_connections: int | None = Field(
        default=None,
        ge=0,
    )

    database_size_bytes: int | None = Field(
        default=None,
        ge=0,
    )

    checked_at: datetime


class SystemRuntimeResponse(ResponseSchema):
    """Application runtime configuration summary."""

    application_name: str = "TeleForward"

    environment: str

    debug: bool

    timezone: str

    database_type: DatabaseTypeSchema

    scheduler_enabled: bool

    telegram_enabled: bool

    webhook_enabled: bool

    started_at: datetime | None = None

    uptime_seconds: float = Field(
        ge=0,
    )


class SystemResourceResponse(ResponseSchema):
    """Host or container resource utilization."""

    cpu_percent: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )

    memory_total_bytes: int | None = Field(
        default=None,
        ge=0,
    )

    memory_used_bytes: int | None = Field(
        default=None,
        ge=0,
    )

    memory_percent: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )

    process_memory_bytes: int | None = Field(
        default=None,
        ge=0,
    )

    process_cpu_percent: float | None = Field(
        default=None,
        ge=0,
    )

    measured_at: datetime


class SystemOverviewResponse(ResponseSchema):
    """Combined system overview for the administration dashboard."""

    version: SystemVersionResponse

    health: SystemHealthResponse

    runtime: SystemRuntimeResponse

    storage: SystemStorageResponse

    database: SystemDatabaseResponse

    resources: SystemResourceResponse
