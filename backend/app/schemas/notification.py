
"""
TeleForward notification schemas.

Defines:
- Notification categories and severity.
- Notification delivery channels and statuses.
- Notification listing filters.
- Notification responses.
- Notification preference settings.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class NotificationTypeSchema(StrEnum):
    """Application notification categories."""

    SYSTEM = "system"
    TELEGRAM = "telegram"
    FORWARDING = "forwarding"
    QUEUE = "queue"
    SECURITY = "security"
    BACKUP = "backup"
    ERROR = "error"


class NotificationSeveritySchema(StrEnum):
    """Notification severity levels."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationChannelSchema(StrEnum):
    """Supported notification delivery channels."""

    IN_APP = "in_app"
    EMAIL = "email"
    TELEGRAM = "telegram"
    WEBHOOK = "webhook"


class NotificationDeliveryStatusSchema(StrEnum):
    """External notification delivery lifecycle."""

    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


class NotificationListQuery(RequestSchema):
    """Filtering parameters for notification listings."""

    notification_type: NotificationTypeSchema | None = None
    severity: NotificationSeveritySchema | None = None

    is_read: bool | None = None

    date_from: datetime | None = None
    date_to: datetime | None = None

    search: str | None = Field(
        default=None,
        max_length=500,
    )


class NotificationResponse(ResponseSchema):
    """Application notification representation."""

    id: int

    notification_type: NotificationTypeSchema
    severity: NotificationSeveritySchema

    title: str
    message: str

    data: dict[str, object] = Field(
        default_factory=dict,
    )

    is_read: bool = False
    read_at: datetime | None = None

    created_at: datetime


class NotificationSummaryResponse(ResponseSchema):
    """Compact notification representation for dashboard listings."""

    id: int

    notification_type: NotificationTypeSchema
    severity: NotificationSeveritySchema

    title: str
    is_read: bool

    created_at: datetime


class NotificationPreferenceResponse(ResponseSchema):
    """Notification preferences for an application user."""

    in_app_enabled: bool = True
    email_enabled: bool = False
    telegram_enabled: bool = False
    webhook_enabled: bool = False

    notify_on_forwarding_failure: bool = True
    notify_on_telegram_disconnect: bool = True
    notify_on_queue_failure: bool = True
    notify_on_backup_failure: bool = True
    notify_on_security_event: bool = True


class NotificationPreferenceUpdateRequest(RequestSchema):
    """Request to update notification preferences."""

    in_app_enabled: bool | None = None
    email_enabled: bool | None = None
    telegram_enabled: bool | None = None
    webhook_enabled: bool | None = None

    notify_on_forwarding_failure: bool | None = None
    notify_on_telegram_disconnect: bool | None = None
    notify_on_queue_failure: bool | None = None
    notify_on_backup_failure: bool | None = None
    notify_on_security_event: bool | None = None


class NotificationDeliveryResponse(ResponseSchema):
    """Result of delivering a notification through a channel."""

    notification_id: int

    channel: NotificationChannelSchema
    status: NotificationDeliveryStatusSchema

    delivered_at: datetime | None = None
    error_message: str | None = None


class NotificationMarkReadResponse(ResponseSchema):
    """Result of marking a notification as read."""

    notification_id: int
    is_read: bool
    read_at: datetime | None = None
