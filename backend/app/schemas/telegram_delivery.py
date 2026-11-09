
"""
TeleForward Telegram delivery schemas.

Defines:
- Telegram message delivery modes.
- Delivery request and destination specifications.
- Individual destination delivery results.
- Aggregate delivery responses.
- Delivery status and error representations.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import RequestSchema, ResponseSchema


class TelegramDeliveryModeSchema(StrEnum):
    """Supported Telegram message delivery modes."""

    FORWARD = "forward"
    COPY = "copy"


class TelegramDeliveryStatusSchema(StrEnum):
    """Lifecycle states of a Telegram delivery operation."""

    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    PARTIALLY_DELIVERED = "partially_delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TelegramDeliveryErrorCodeSchema(StrEnum):
    """Normalized Telegram delivery error categories."""

    FLOOD_WAIT = "flood_wait"
    CHAT_NOT_FOUND = "chat_not_found"
    MESSAGE_NOT_FOUND = "message_not_found"
    PERMISSION_DENIED = "permission_denied"
    WRITE_FORBIDDEN = "write_forbidden"
    USER_BANNED = "user_banned"
    MEDIA_INVALID = "media_invalid"
    MESSAGE_TOO_LONG = "message_too_long"
    DUPLICATE = "duplicate"
    ACCOUNT_DISCONNECTED = "account_disconnected"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    TELEGRAM_ERROR = "telegram_error"
    UNKNOWN = "unknown"


class TelegramDeliveryDestinationSchema(RequestSchema):
    """Destination chat for a delivery operation."""

    chat_id: int

    topic_id: int | None = Field(
        default=None,
        gt=0,
    )


class TelegramDeliveryRequest(RequestSchema):
    """Request to forward or copy a Telegram message."""

    account_id: int = Field(
        gt=0,
    )

    source_chat_id: int

    source_message_ids: list[int] = Field(
        min_length=1,
        max_length=100,
    )

    destinations: list[TelegramDeliveryDestinationSchema] = Field(
        min_length=1,
        max_length=50,
    )

    mode: TelegramDeliveryModeSchema = (
        TelegramDeliveryModeSchema.FORWARD
    )

    silent: bool = False

    schedule_at: datetime | None = None

    disable_notification: bool = False

    protect_content: bool = False

    @model_validator(mode="after")
    def validate_delivery_request(self):
        """Validate message IDs and destination uniqueness."""

        if any(message_id <= 0 for message_id in self.source_message_ids):
            raise ValueError(
                "All source message IDs must be positive"
            )

        if len(set(self.source_message_ids)) != len(
            self.source_message_ids
        ):
            raise ValueError(
                "Source message IDs must not contain duplicates"
            )

        destination_keys = [
            (destination.chat_id, destination.topic_id)
            for destination in self.destinations
        ]

        if len(destination_keys) != len(set(destination_keys)):
            raise ValueError(
                "Destination chats and topics must be unique"
            )

        if (
            self.schedule_at is not None
            and self.schedule_at.tzinfo is None
        ):
            raise ValueError(
                "schedule_at must be timezone-aware"
            )

        return self


class TelegramDeliveryDestinationResult(ResponseSchema):
    """Delivery result for one destination."""

    destination_chat_id: int

    topic_id: int | None = None

    status: TelegramDeliveryStatusSchema

    delivered_message_ids: list[int] = Field(
        default_factory=list,
    )

    error_code: TelegramDeliveryErrorCodeSchema | None = None

    error_message: str | None = Field(
        default=None,
        max_length=2000,
    )

    retry_after_seconds: int | None = Field(
        default=None,
        ge=0,
    )

    delivered_at: datetime | None = None


class TelegramDeliveryResponse(ResponseSchema):
    """Aggregate result of a Telegram delivery operation."""

    id: int

    account_id: int

    source_chat_id: int

    source_message_ids: list[int]

    mode: TelegramDeliveryModeSchema

    status: TelegramDeliveryStatusSchema

    destinations: list[TelegramDeliveryDestinationResult] = Field(
        default_factory=list,
    )

    total_destinations: int = Field(
        ge=0,
    )

    successful_destinations: int = Field(
        ge=0,
    )

    failed_destinations: int = Field(
        ge=0,
    )

    created_at: datetime

    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_destination_counts(self):
        """Ensure aggregate destination counts are consistent."""

        if (
            self.successful_destinations
            + self.failed_destinations
            > self.total_destinations
        ):
            raise ValueError(
                "Successful and failed destination counts "
                "cannot exceed total destinations"
            )

        if self.total_destinations != len(self.destinations):
            raise ValueError(
                "total_destinations must match the destinations list"
            )

        return self


class TelegramDeliveryCancelRequest(RequestSchema):
    """Request to cancel a pending delivery operation."""

    reason: str | None = Field(
        default=None,
        max_length=500,
    )


class TelegramDeliveryRetryRequest(RequestSchema):
    """Request to retry failed destinations."""

    destination_chat_ids: list[int] | None = Field(
        default=None,
        max_length=50,
    )

    @model_validator(mode="after")
    def validate_destination_ids(self):
        """Reject duplicate destination identifiers."""

        if self.destination_chat_ids is not None:
            if len(self.destination_chat_ids) != len(
                set(self.destination_chat_ids)
            ):
                raise ValueError(
                    "Destination chat IDs must not contain duplicates"
                )

        return self
