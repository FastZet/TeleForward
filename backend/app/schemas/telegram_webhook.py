
"""
TeleForward webhook schemas.

Defines:
- Outbound webhook configuration.
- Webhook event subscriptions.
- Webhook update requests.
- Webhook delivery status and attempt information.
- Webhook health information.

Webhook secrets must be encrypted at rest and must never be
returned in API responses.
"""

from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator

from app.schemas.common import RequestSchema, ResponseSchema


class WebhookEventTypeSchema(StrEnum):
    """Events that can be delivered to configured webhooks."""

    TELEGRAM_ACCOUNT_CONNECTED = "telegram.account.connected"
    TELEGRAM_ACCOUNT_DISCONNECTED = "telegram.account.disconnected"
    TELEGRAM_ACCOUNT_AUTH_FAILED = "telegram.account.auth_failed"

    TELEGRAM_MESSAGE_RECEIVED = "telegram.message.received"
    TELEGRAM_MESSAGE_EDITED = "telegram.message.edited"
    TELEGRAM_MESSAGE_DELETED = "telegram.message.deleted"

    TELEGRAM_CHAT_DISCOVERED = "telegram.chat.discovered"
    TELEGRAM_CHAT_UPDATED = "telegram.chat.updated"

    FORWARDING_STARTED = "forwarding.started"
    FORWARDING_COMPLETED = "forwarding.completed"
    FORWARDING_FAILED = "forwarding.failed"

    BACKFILL_STARTED = "backfill.started"
    BACKFILL_COMPLETED = "backfill.completed"
    BACKFILL_FAILED = "backfill.failed"

    QUEUE_JOB_FAILED = "queue.job.failed"
    SYSTEM_ERROR = "system.error"


class WebhookStatusSchema(StrEnum):
    """Webhook operational status."""

    ACTIVE = "active"
    DISABLED = "disabled"
    FAILING = "failing"
    SUSPENDED = "suspended"


class WebhookDeliveryStatusSchema(StrEnum):
    """Individual webhook delivery states."""

    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


class WebhookCreateRequest(RequestSchema):
    """Create an outbound webhook endpoint."""

    name: str = Field(
        min_length=1,
        max_length=150,
    )

    url: str = Field(
        max_length=2048,
    )

    secret: SecretStr | None = Field(
        default=None,
        min_length=16,
        max_length=256,
    )

    events: list[WebhookEventTypeSchema] = Field(
        min_length=1,
        max_length=50,
    )

    enabled: bool = True

    timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
    )

    max_retries: int = Field(
        default=5,
        ge=0,
        le=20,
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Require an absolute HTTPS webhook URL."""

        parsed = urlparse(value)

        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(
                "Webhook URL must be an absolute HTTPS URL"
            )

        if parsed.username or parsed.password:
            raise ValueError(
                "Webhook URL must not contain embedded credentials"
            )

        if parsed.fragment:
            raise ValueError(
                "Webhook URL must not contain a fragment"
            )

        return value

    @field_validator("events")
    @classmethod
    def validate_events(
        cls,
        value: list[WebhookEventTypeSchema],
    ) -> list[WebhookEventTypeSchema]:
        """Reject duplicate event subscriptions."""

        if len(value) != len(set(value)):
            raise ValueError(
                "Webhook event subscriptions must not contain duplicates"
            )

        return value


class WebhookUpdateRequest(RequestSchema):
    """Update an existing outbound webhook."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
    )

    url: str | None = Field(
        default=None,
        max_length=2048,
    )

    secret: SecretStr | None = Field(
        default=None,
        min_length=16,
        max_length=256,
    )

    events: list[WebhookEventTypeSchema] | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )

    enabled: bool | None = None

    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        le=60,
    )

    max_retries: int | None = Field(
        default=None,
        ge=0,
        le=20,
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        """Validate a replacement webhook URL."""

        if value is None:
            return value

        parsed = urlparse(value)

        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(
                "Webhook URL must be an absolute HTTPS URL"
            )

        if parsed.username or parsed.password:
            raise ValueError(
                "Webhook URL must not contain embedded credentials"
            )

        if parsed.fragment:
            raise ValueError(
                "Webhook URL must not contain a fragment"
            )

        return value

    @field_validator("events")
    @classmethod
    def validate_events(
        cls,
        value: list[WebhookEventTypeSchema] | None,
    ) -> list[WebhookEventTypeSchema] | None:
        """Reject duplicate event subscriptions."""

        if value is not None and len(value) != len(set(value)):
            raise ValueError(
                "Webhook event subscriptions must not contain duplicates"
            )

        return value


class WebhookResponse(ResponseSchema):
    """Public webhook configuration representation."""

    id: int

    name: str

    url: str

    events: list[WebhookEventTypeSchema]

    status: WebhookStatusSchema

    enabled: bool

    timeout_seconds: int

    max_retries: int

    consecutive_failures: int = Field(
        default=0,
        ge=0,
    )

    last_delivery_at: datetime | None = None

    last_success_at: datetime | None = None

    created_at: datetime

    updated_at: datetime


class WebhookDeliveryResponse(ResponseSchema):
    """Information about an individual webhook delivery."""

    id: int

    webhook_id: int

    event_type: WebhookEventTypeSchema

    status: WebhookDeliveryStatusSchema

    attempt_count: int = Field(
        default=0,
        ge=0,
    )

    http_status_code: int | None = Field(
        default=None,
        ge=100,
        le=599,
    )

    response_excerpt: str | None = Field(
        default=None,
        max_length=1000,
    )

    next_attempt_at: datetime | None = None

    delivered_at: datetime | None = None

    created_at: datetime


class WebhookHealthResponse(ResponseSchema):
    """Webhook health and delivery statistics."""

    webhook_id: int

    status: WebhookStatusSchema

    total_deliveries: int = Field(
        default=0,
        ge=0,
    )

    successful_deliveries: int = Field(
        default=0,
        ge=0,
    )

    failed_deliveries: int = Field(
        default=0,
        ge=0,
    )

    consecutive_failures: int = Field(
        default=0,
        ge=0,
    )

    last_delivery_at: datetime | None = None

    last_success_at: datetime | None = None

    checked_at: datetime
