
"""
TeleForward activity and audit-log schemas.

Defines:
- Activity event categories.
- Audit event severity.
- Activity listing filters.
- Activity history responses.
- Security audit-log responses.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class ActivityCategorySchema(StrEnum):
    """Categories of application activity."""

    AUTHENTICATION = "authentication"
    TELEGRAM = "telegram"
    FORWARDING = "forwarding"
    MESSAGE = "message"
    QUEUE = "queue"
    BACKUP = "backup"
    SETTINGS = "settings"
    NOTIFICATION = "notification"
    SYSTEM = "system"


class ActivitySeveritySchema(StrEnum):
    """Severity levels for recorded activity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ActivityEventTypeSchema(StrEnum):
    """Known application activity events."""

    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    LOGIN_FAILED = "login_failed"
    PASSWORD_CHANGED = "password_changed"

    TELEGRAM_ACCOUNT_ADDED = "telegram_account_added"
    TELEGRAM_ACCOUNT_CONNECTED = "telegram_account_connected"
    TELEGRAM_ACCOUNT_DISCONNECTED = "telegram_account_disconnected"
    TELEGRAM_ACCOUNT_REMOVED = "telegram_account_removed"

    FORWARDING_RULE_CREATED = "forwarding_rule_created"
    FORWARDING_RULE_UPDATED = "forwarding_rule_updated"
    FORWARDING_RULE_ENABLED = "forwarding_rule_enabled"
    FORWARDING_RULE_DISABLED = "forwarding_rule_disabled"
    FORWARDING_RULE_DELETED = "forwarding_rule_deleted"

    MESSAGE_FORWARDED = "message_forwarded"
    MESSAGE_FORWARD_FAILED = "message_forward_failed"

    BACKUP_CREATED = "backup_created"
    BACKUP_RESTORED = "backup_restored"
    BACKUP_FAILED = "backup_failed"

    SETTINGS_UPDATED = "settings_updated"

    SYSTEM_STARTED = "system_started"
    SYSTEM_STOPPED = "system_stopped"
    SYSTEM_ERROR = "system_error"


class ActivityListQuery(RequestSchema):
    """Filtering parameters for activity history."""

    category: ActivityCategorySchema | None = None
    event_type: ActivityEventTypeSchema | None = None
    severity: ActivitySeveritySchema | None = None

    actor_user_id: int | None = Field(
        default=None,
        gt=0,
    )

    date_from: datetime | None = None
    date_to: datetime | None = None

    search: str | None = Field(
        default=None,
        max_length=500,
    )


class ActivityResponse(ResponseSchema):
    """Application activity-history entry."""

    id: int

    category: ActivityCategorySchema
    event_type: ActivityEventTypeSchema
    severity: ActivitySeveritySchema

    title: str
    description: str | None = None

    actor_user_id: int | None = None
    actor_type: str | None = None

    related_entity_type: str | None = None
    related_entity_id: int | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    created_at: datetime


class AuditLogResponse(ResponseSchema):
    """Security-relevant audit-log entry."""

    id: int

    event_type: str
    severity: ActivitySeveritySchema

    actor_user_id: int | None = None

    ip_address: str | None = None
    user_agent: str | None = None

    resource_type: str | None = None
    resource_id: str | None = None

    action: str

    success: bool

    details: dict[str, Any] = Field(
        default_factory=dict,
    )

    created_at: datetime


class AuditLogListQuery(RequestSchema):
    """Filtering parameters for security audit logs."""

    event_type: str | None = Field(
        default=None,
        max_length=100,
    )

    severity: ActivitySeveritySchema | None = None

    actor_user_id: int | None = Field(
        default=None,
        gt=0,
    )

    success: bool | None = None

    ip_address: str | None = Field(
        default=None,
        max_length=45,
    )

    date_from: datetime | None = None
    date_to: datetime | None = None

    search: str | None = Field(
        default=None,
        max_length=500,
    )
