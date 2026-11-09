
"""
TeleForward audit log schemas.

Defines:
- Audit event categories and severity.
- Audit actor and resource information.
- Audit event representations.
- Audit log filtering and pagination.

Audit records should be append-only. Sensitive credentials, Telegram
session data, authentication codes and secret values must never be
stored in audit event metadata.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import RequestSchema, ResponseSchema


class AuditActionCategorySchema(StrEnum):
    """Categories of auditable application actions."""

    AUTHENTICATION = "authentication"
    USER_MANAGEMENT = "user_management"
    SETTINGS = "settings"
    TELEGRAM_ACCOUNT = "telegram_account"
    TELEGRAM_CHAT = "telegram_chat"
    FORWARDING = "forwarding"
    FILTERING = "filtering"
    TRANSFORMATION = "transformation"
    CLASSIFICATION = "classification"
    SCHEDULING = "scheduling"
    BACKFILL = "backfill"
    RECOVERY = "recovery"
    WEBHOOK = "webhook"
    BACKUP = "backup"
    SYSTEM = "system"


class AuditSeveritySchema(StrEnum):
    """Audit event severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditOutcomeSchema(StrEnum):
    """Outcome of an auditable action."""

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    PARTIAL = "partial"


class AuditActorTypeSchema(StrEnum):
    """Types of actors that can initiate application actions."""

    USER = "user"
    SYSTEM = "system"
    WORKER = "worker"
    API_KEY = "api_key"


class AuditActorResponse(ResponseSchema):
    """Identity of the actor responsible for an audit event."""

    actor_type: AuditActorTypeSchema

    actor_id: int | None = None

    username: str | None = Field(
        default=None,
        max_length=255,
    )

    display_name: str | None = Field(
        default=None,
        max_length=255,
    )


class AuditResourceResponse(ResponseSchema):
    """Reference to the resource affected by an action."""

    resource_type: str = Field(
        min_length=1,
        max_length=100,
    )

    resource_id: str | None = Field(
        default=None,
        max_length=255,
    )

    resource_name: str | None = Field(
        default=None,
        max_length=255,
    )


class AuditEventResponse(ResponseSchema):
    """A recorded application audit event."""

    id: int

    event_type: str = Field(
        min_length=1,
        max_length=150,
    )

    category: AuditActionCategorySchema

    severity: AuditSeveritySchema

    outcome: AuditOutcomeSchema

    actor: AuditActorResponse

    resource: AuditResourceResponse | None = None

    description: str = Field(
        min_length=1,
        max_length=2000,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    request_id: str | None = Field(
        default=None,
        max_length=128,
    )

    ip_address: str | None = Field(
        default=None,
        max_length=45,
    )

    user_agent: str | None = Field(
        default=None,
        max_length=1000,
    )

    occurred_at: datetime


class AuditLogQuery(RequestSchema):
    """Filters for retrieving audit events."""

    category: AuditActionCategorySchema | None = None

    severity: AuditSeveritySchema | None = None

    outcome: AuditOutcomeSchema | None = None

    actor_id: int | None = Field(
        default=None,
        gt=0,
    )

    actor_type: AuditActorTypeSchema | None = None

    resource_type: str | None = Field(
        default=None,
        max_length=100,
    )

    resource_id: str | None = Field(
        default=None,
        max_length=255,
    )

    event_type: str | None = Field(
        default=None,
        max_length=150,
    )

    request_id: str | None = Field(
        default=None,
        max_length=128,
    )

    search: str | None = Field(
        default=None,
        max_length=500,
    )

    start_date: datetime | None = None

    end_date: datetime | None = None

    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    offset: int = Field(
        default=0,
        ge=0,
    )

    @model_validator(mode="after")
    def validate_date_range(self):
        """Validate audit filtering date boundaries."""

        if self.start_date is not None and self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError(
                    "end_date must be later than or equal to start_date"
                )

            if (
                self.start_date.tzinfo is None
                or self.end_date.tzinfo is None
            ):
                raise ValueError(
                    "Audit date boundaries must be timezone-aware"
                )

        return self


class AuditLogListResponse(ResponseSchema):
    """Paginated audit event results."""

    items: list[AuditEventResponse] = Field(
        default_factory=list,
    )

    total: int = Field(
        ge=0,
    )

    limit: int = Field(
        ge=1,
    )

    offset: int = Field(
        ge=0,
    )

    has_more: bool = False


class AuditRetentionUpdateRequest(RequestSchema):
    """Update the audit log retention period."""

    retention_days: int = Field(
        ge=30,
        le=3650,
    )

    archive_before_deletion: bool = True
