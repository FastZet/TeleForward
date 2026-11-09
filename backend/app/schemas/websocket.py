
"""
TeleForward WebSocket schemas.

Defines:
- WebSocket event types.
- Standardised event envelopes.
- Client subscription requests.
- Connection and subscription responses.
- Real-time error messages.
- Heartbeat messages.

Authentication, connection management, event routing, and
subscription authorisation belong to the WebSocket service.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import RequestSchema, ResponseSchema


class WebSocketEventType(StrEnum):
    """Supported real-time application event types."""

    CONNECTION_ESTABLISHED = "connection.established"
    CONNECTION_CLOSED = "connection.closed"

    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat.ack"

    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_REMOVED = "subscription.removed"

    FORWARDING_STARTED = "forwarding.started"
    FORWARDING_COMPLETED = "forwarding.completed"
    FORWARDING_FAILED = "forwarding.failed"

    MESSAGE_RECEIVED = "message.received"
    MESSAGE_DELIVERED = "message.delivered"

    QUEUE_UPDATED = "queue.updated"
    QUEUE_JOB_STARTED = "queue.job_started"
    QUEUE_JOB_COMPLETED = "queue.job_completed"
    QUEUE_JOB_FAILED = "queue.job_failed"

    TELEGRAM_ACCOUNT_CONNECTED = "telegram.account_connected"
    TELEGRAM_ACCOUNT_DISCONNECTED = "telegram.account_disconnected"

    BACKFILL_PROGRESS = "backfill.progress"
    BACKFILL_COMPLETED = "backfill.completed"
    BACKFILL_FAILED = "backfill.failed"

    RECOVERY_PROGRESS = "recovery.progress"
    RECOVERY_COMPLETED = "recovery.completed"
    RECOVERY_FAILED = "recovery.failed"

    SCHEDULE_EXECUTED = "schedule.executed"
    SCHEDULE_FAILED = "schedule.failed"

    NOTIFICATION_CREATED = "notification.created"

    METRICS_UPDATED = "metrics.updated"

    SYSTEM_STATUS_CHANGED = "system.status_changed"

    ERROR = "error"


class WebSocketConnectionStatus(StrEnum):
    """WebSocket connection lifecycle states."""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class WebSocketSubscriptionTopic(StrEnum):
    """Supported real-time subscription topics."""

    ALL = "all"
    FORWARDING = "forwarding"
    MESSAGES = "messages"
    QUEUE = "queue"
    TELEGRAM_ACCOUNTS = "telegram_accounts"
    BACKFILL = "backfill"
    RECOVERY = "recovery"
    SCHEDULING = "scheduling"
    NOTIFICATIONS = "notifications"
    METRICS = "metrics"
    SYSTEM = "system"


class WebSocketErrorCode(StrEnum):
    """Standardised WebSocket error codes."""

    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    INVALID_MESSAGE = "invalid_message"
    INVALID_SUBSCRIPTION = "invalid_subscription"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"


class WebSocketEventEnvelope(ResponseSchema):
    """Standard event envelope sent by the server."""

    event_id: str = Field(
        min_length=1,
        max_length=128,
    )

    event_type: WebSocketEventType

    timestamp: datetime

    sequence: int | None = Field(
        default=None,
        ge=0,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=128,
    )

    data: dict[str, Any] = Field(
        default_factory=dict,
    )


class WebSocketSubscriptionRequest(RequestSchema):
    """Client request to subscribe to real-time events."""

    topics: list[WebSocketSubscriptionTopic] = Field(
        min_length=1,
        max_length=20,
    )

    account_ids: list[int] = Field(
        default_factory=list,
        max_length=100,
    )

    forwarding_rule_ids: list[int] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_subscription(self):
        """Validate subscription filters."""

        if len(self.topics) != len(set(self.topics)):
            raise ValueError(
                "Subscription topics cannot contain duplicates"
            )

        if (
            WebSocketSubscriptionTopic.ALL in self.topics
            and len(self.topics) > 1
        ):
            raise ValueError(
                "The all topic cannot be combined with other topics"
            )

        if any(account_id <= 0 for account_id in self.account_ids):
            raise ValueError(
                "All account IDs must be positive"
            )

        if len(self.account_ids) != len(set(self.account_ids)):
            raise ValueError(
                "Account IDs cannot contain duplicates"
            )

        if any(
            rule_id <= 0
            for rule_id in self.forwarding_rule_ids
        ):
            raise ValueError(
                "All forwarding rule IDs must be positive"
            )

        if len(self.forwarding_rule_ids) != len(
            set(self.forwarding_rule_ids)
        ):
            raise ValueError(
                "Forwarding rule IDs cannot contain duplicates"
            )

        return self


class WebSocketSubscriptionResponse(ResponseSchema):
    """Server acknowledgement of a subscription request."""

    subscription_id: str = Field(
        min_length=1,
        max_length=128,
    )

    topics: list[WebSocketSubscriptionTopic]

    account_ids: list[int] = Field(
        default_factory=list,
    )

    forwarding_rule_ids: list[int] = Field(
        default_factory=list,
    )

    created_at: datetime


class WebSocketUnsubscriptionRequest(RequestSchema):
    """Client request to remove an existing subscription."""

    subscription_ids: list[str] = Field(
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_subscription_ids(self):
        """Ensure subscription identifiers are unique."""

        if len(self.subscription_ids) != len(
            set(self.subscription_ids)
        ):
            raise ValueError(
                "Subscription IDs cannot contain duplicates"
            )

        return self


class WebSocketConnectionResponse(ResponseSchema):
    """Connection establishment or status response."""

    connection_id: str = Field(
        min_length=1,
        max_length=128,
    )

    status: WebSocketConnectionStatus

    connected_at: datetime | None = None

    server_time: datetime

    heartbeat_interval_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
    )


class WebSocketHeartbeatRequest(RequestSchema):
    """Client heartbeat message."""

    timestamp: datetime

    sequence: int = Field(
        ge=0,
    )


class WebSocketHeartbeatResponse(ResponseSchema):
    """Server heartbeat acknowledgement."""

    timestamp: datetime

    server_time: datetime

    sequence: int = Field(
        ge=0,
    )


class WebSocketErrorResponse(ResponseSchema):
    """Structured WebSocket error response."""

    code: WebSocketErrorCode

    message: str = Field(
        min_length=1,
        max_length=1000,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=128,
    )

    timestamp: datetime
