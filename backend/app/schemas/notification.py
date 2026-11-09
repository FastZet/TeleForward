
"""
TeleForward notification schemas.

Defines:
- Notification channels and event categories.
- Notification preferences.
- Notification creation and delivery status.
- Notification history and pagination.
- Notification read-state management.

Actual delivery, retries, channel integrations, and user
authorisation belong to the notification service.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import RequestSchema, ResponseSchema


class NotificationChannel(StrEnum):
    """Supported notification delivery channels."""

    IN_APP = "in_app"
    EMAIL = "email"
    TELEGRAM = "telegram"
    WEBHOOK = "webhook"


class NotificationEventType(StrEnum):
    """Application events that can generate notifications."""

    FORWARDING_SUCCESS = "forwarding_success"
    FORWARDING_FAILURE = "forwarding_failure"
    TELEGRAM_DISCONNECTED = "telegram_disconnected"
    TELEGRAM_RECONNECTED = "telegram_reconnected"
    QUEUE_FAILURE = "queue_failure"
    BACKFILL_COMPLETED = "backfill_completed"
    BACKFILL_FAILED = "backfill_failed"
    RECOVERY_COMPLETED = "recovery_completed"
    RECOVERY_FAILED = "recovery_failed"
    SCHEDULE_EXECUTED = "schedule_executed"
    SCHEDULE_FAILED = "schedule_failed"
    SYSTEM_WARNING = "system_warning"
    SYSTEM_ERROR = "system_error"
    SECURITY_EVENT = "security_event"


class NotificationSeverity(StrEnum):
    """Notification importance levels."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationDeliveryStatus(StrEnum):
    """Delivery lifecycle states."""

    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class NotificationPreferencesUpdateRequest(RequestSchema):
    """Request to update notification preferences."""

    enabled: bool = True

    enabled_channels: list[NotificationChannel] = Field(
        default_factory=lambda: [
            NotificationChannel.IN_APP
        ],
    )

    enabled_events: list[NotificationEventType] = Field(
        default_factory=lambda: list(NotificationEventType),
    )

    minimum_severity: NotificationSeverity = (
        NotificationSeverity.INFO
    )

    quiet_hours_enabled: bool = False

    quiet_hours_start: str | None = Field(
        default=None,
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
    )

    quiet_hours_end: str | None = Field(
        default=None,
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
    )

    timezone: str = Field(
        default="UTC",
        min_length=1,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_preferences(self):
        """Validate notification preference combinations."""

        if len(self.enabled_channels) != len(set(self.enabled_channels)):
            raise ValueError(
                "enabled_channels cannot contain duplicates"
            )

        if len(self.enabled_events) != len(set(self.enabled_events)):
            raise ValueError(
                "enabled_events cannot contain duplicates"
            )

        if self.quiet_hours_enabled:
            if (
                self.quiet_hours_start is None
                or self.quiet_hours_end is None
            ):
                raise ValueError(
                    "Both quiet-hours boundaries are required when quiet hours are enabled"
                )

            if self.quiet_hours_start == self.quiet_hours_end:
                raise ValueError(
                    "Quiet-hours start and end cannot be identical"
                )

        return self


class NotificationPreferencesResponse(ResponseSchema):
    """Stored notification preferences."""

    enabled: bool

    enabled_channels: list[NotificationChannel]

    enabled_events: list[NotificationEventType]

    minimum_severity: NotificationSeverity

    quiet_hours_enabled: bool

    quiet_hours_start: str | None = None

    quiet_hours_end: str | None = None

    timezone: str

    updated_at: datetime


class NotificationCreateRequest(RequestSchema):
    """Request to create an application notification."""

    event_type: NotificationEventType

    severity: NotificationSeverity = NotificationSeverity.INFO

    title: str = Field(
        min_length=1,
        max_length=255,
    )

    message: str = Field(
        min_length=1,
        max_length=5000,
    )

    account_id: int | None = Field(
        default=None,
        gt=0,
    )

    forwarding_rule_id: int | None = Field(
        default=None,
        gt=0,
    )

    metadata: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
    )


class NotificationResponse(ResponseSchema):
    """Notification information returned by the API."""

    id: int = Field(gt=0)

    event_type: NotificationEventType

    severity: NotificationSeverity

    title: str

    message: str

    is_read: bool = False

    read_at: datetime | None = None

    account_id: int | None = Field(
        default=None,
        gt=0,
    )

    forwarding_rule_id: int | None = Field(
        default=None,
        gt=0,
    )

    created_at: datetime

    @model_validator(mode="after")
    def validate_read_state(self):
        """Ensure read-state timestamps are consistent."""

        if self.is_read and self.read_at is None:
            raise ValueError(
                "read_at is required for a read notification"
            )

        if not self.is_read and self.read_at is not None:
            raise ValueError(
                "Unread notifications cannot have read_at set"
            )

        return self


class NotificationDeliveryResponse(ResponseSchema):
    """Delivery status for one notification channel."""

    id: int = Field(gt=0)

    channel: NotificationChannel

    status: NotificationDeliveryStatus

    attempt_count: int = Field(
        default=0,
        ge=0,
    )

    last_attempt_at: datetime | None = None

    delivered_at: datetime | None = None

    error_message: str | None = Field(
        default=None,
        max_length=1000,
    )


class NotificationDetailResponse(NotificationResponse):
    """Notification with its channel delivery information."""

    deliveries: list[NotificationDeliveryResponse] = Field(
        default_factory=list,
    )


class NotificationListResponse(ResponseSchema):
    """Paginated notification history."""

    items: list[NotificationResponse] = Field(
        default_factory=list,
    )

    total: int = Field(
        default=0,
        ge=0,
    )

    unread_count: int = Field(
        default=0,
        ge=0,
    )

    page: int = Field(
        default=1,
        ge=1,
    )

    page_size: int = Field(
        default=20,
        ge=1,
        le=100,
    )


class NotificationReadRequest(RequestSchema):
    """Request to mark notifications as read."""

    notification_ids: list[int] = Field(
        min_length=1,
        max_length=500,
    )

    @model_validator(mode="after")
    def validate_notification_ids(self):
        """Ensure notification identifiers are valid and unique."""

        if any(notification_id <= 0 for notification_id in self.notification_ids):
            raise ValueError(
                "All notification IDs must be positive"
            )

        if len(self.notification_ids) != len(set(self.notification_ids)):
            raise ValueError(
                "notification_ids cannot contain duplicates"
            )

        return self


class NotificationReadResponse(ResponseSchema):
    """Result of a notification read-state operation."""

    updated_count: int = Field(
        ge=0,
    )

    unread_count: int = Field(
        ge=0,
    )

    updated_at: datetime


class NotificationDeleteRequest(RequestSchema):
    """Request to delete selected notifications."""

    notification_ids: list[int] = Field(
        min_length=1,
        max_length=500,
    )

    @model_validator(mode="after")
    def validate_notification_ids(self):
        """Ensure notification identifiers are valid and unique."""

        if any(notification_id <= 0 for notification_id in self.notification_ids):
            raise ValueError(
                "All notification IDs must be positive"
            )

        if len(self.notification_ids) != len(set(self.notification_ids)):
            raise ValueError(
                "notification_ids cannot contain duplicates"
            )

        return self


class NotificationDeleteResponse(ResponseSchema):
    """Result of a notification deletion operation."""

    deleted_count: int = Field(
        ge=0,
    )

    deleted_at: datetime
