
"""
TeleForward dashboard schemas.

Defines:
- Dashboard overview metrics.
- Telegram account status summaries.
- Forwarding activity statistics.
- Queue statistics.
- Recent activity entries.
- System health summaries.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import ResponseSchema


class DashboardHealthStatusSchema(StrEnum):
    """Overall application health indicators."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class DashboardAccountStatusSchema(StrEnum):
    """Telegram account connectivity indicators."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class DashboardOverviewResponse(ResponseSchema):
    """High-level dashboard metrics."""

    health_status: DashboardHealthStatusSchema

    total_accounts: int = Field(ge=0)
    connected_accounts: int = Field(ge=0)

    total_chats: int = Field(ge=0)

    total_forwarding_rules: int = Field(ge=0)
    active_forwarding_rules: int = Field(ge=0)

    messages_processed: int = Field(ge=0)
    messages_forwarded: int = Field(ge=0)
    messages_failed: int = Field(ge=0)

    pending_queue_tasks: int = Field(ge=0)
    processing_queue_tasks: int = Field(ge=0)
    failed_queue_tasks: int = Field(ge=0)

    unread_notifications: int = Field(ge=0)

    generated_at: datetime


class DashboardAccountSummary(ResponseSchema):
    """Telegram account information for dashboard widgets."""

    id: int

    phone_number: str
    display_name: str | None = None

    status: DashboardAccountStatusSchema

    last_connected_at: datetime | None = None
    last_error: str | None = None


class DashboardForwardingStatistics(ResponseSchema):
    """Forwarding activity aggregated over a reporting period."""

    period_start: datetime
    period_end: datetime

    total_processed: int = Field(ge=0)
    total_forwarded: int = Field(ge=0)
    total_failed: int = Field(ge=0)
    total_skipped: int = Field(ge=0)

    success_rate: float = Field(
        ge=0,
        le=100,
    )


class DashboardTimeSeriesPoint(ResponseSchema):
    """One time-series data point for dashboard charts."""

    timestamp: datetime

    processed: int = Field(ge=0)
    forwarded: int = Field(ge=0)
    failed: int = Field(ge=0)


class DashboardQueueSummary(ResponseSchema):
    """Queue workload summary."""

    pending: int = Field(ge=0)
    processing: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)

    oldest_pending_at: datetime | None = None


class DashboardActivityTypeSchema(StrEnum):
    """Categories of recent dashboard activity."""

    ACCOUNT_CONNECTED = "account_connected"
    ACCOUNT_DISCONNECTED = "account_disconnected"
    RULE_CREATED = "rule_created"
    RULE_UPDATED = "rule_updated"
    RULE_DISABLED = "rule_disabled"
    MESSAGE_FORWARDED = "message_forwarded"
    MESSAGE_FAILED = "message_failed"
    BACKUP_CREATED = "backup_created"
    SYSTEM_WARNING = "system_warning"
    SYSTEM_ERROR = "system_error"


class DashboardActivityResponse(ResponseSchema):
    """Recent operational activity entry."""

    id: int

    activity_type: DashboardActivityTypeSchema

    title: str
    description: str | None = None

    related_entity_type: str | None = None
    related_entity_id: int | None = None

    created_at: datetime


class DashboardSystemStatusResponse(ResponseSchema):
    """Application and infrastructure health summary."""

    overall_status: DashboardHealthStatusSchema

    database_status: DashboardHealthStatusSchema
    telegram_status: DashboardHealthStatusSchema
    queue_status: DashboardHealthStatusSchema
    storage_status: DashboardHealthStatusSchema

    uptime_seconds: float = Field(ge=0)

    checked_at: datetime
