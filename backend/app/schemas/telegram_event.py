
"""
TeleForward Telegram event schemas.

Defines:
- Incoming Telegram event types.
- New message event payloads.
- Message edit and deletion events.
- Event processing status.
- Event metadata and processing results.

These schemas represent internal application event contracts.
They must not be treated as trusted Telegram API payloads.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class TelegramEventTypeSchema(StrEnum):
    """Supported Telegram event types."""

    NEW_MESSAGE = "new_message"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_DELETED = "message_deleted"
    ALBUM_RECEIVED = "album_received"
    CHAT_ACTION = "chat_action"
    CONNECTION_CHANGED = "connection_changed"


class TelegramEventStatusSchema(StrEnum):
    """Telegram event processing states."""

    RECEIVED = "received"
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class TelegramMessageReferenceSchema(RequestSchema):
    """Reference to a Telegram message."""

    account_id: int = Field(
        gt=0,
    )

    chat_id: int

    message_id: int = Field(
        gt=0,
    )

    grouped_id: int | None = None


class TelegramIncomingMessageEvent(RequestSchema):
    """Internal representation of a newly received message."""

    account_id: int = Field(
        gt=0,
    )

    chat_id: int

    message_id: int = Field(
        gt=0,
    )

    grouped_id: int | None = None

    sender_id: int | None = None

    message_text: str | None = Field(
        default=None,
        max_length=100000,
    )

    caption: str | None = Field(
        default=None,
        max_length=100000,
    )

    has_media: bool = False

    media_type: str | None = Field(
        default=None,
        max_length=100,
    )

    reply_to_message_id: int | None = Field(
        default=None,
        gt=0,
    )

    message_date: datetime

    received_at: datetime

    raw_metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class TelegramMessageEditedEvent(RequestSchema):
    """Internal representation of an edited Telegram message."""

    account_id: int = Field(
        gt=0,
    )

    chat_id: int

    message_id: int = Field(
        gt=0,
    )

    message_text: str | None = Field(
        default=None,
        max_length=100000,
    )

    caption: str | None = Field(
        default=None,
        max_length=100000,
    )

    edited_at: datetime

    received_at: datetime

    raw_metadata: dict[str, Any] = Field(
        default_factory=dict,
    )


class TelegramMessageDeletedEvent(RequestSchema):
    """Internal representation of deleted Telegram messages."""

    account_id: int = Field(
        gt=0,
    )

    chat_id: int

    message_ids: list[int] = Field(
        min_length=1,
        max_length=10000,
    )

    received_at: datetime

    def validate_message_ids(self):
        """Validate that message identifiers are positive and unique."""

        if any(message_id <= 0 for message_id in self.message_ids):
            raise ValueError(
                "message_ids must contain positive IDs"
            )

        if len(set(self.message_ids)) != len(self.message_ids):
            raise ValueError(
                "message_ids must not contain duplicates"
            )

        return self


class TelegramEventEnvelope(ResponseSchema):
    """Standard envelope for an application Telegram event."""

    event_id: str = Field(
        min_length=1,
        max_length=128,
    )

    event_type: TelegramEventTypeSchema

    status: TelegramEventStatusSchema = (
        TelegramEventStatusSchema.RECEIVED
    )

    account_id: int = Field(
        gt=0,
    )

    occurred_at: datetime

    received_at: datetime

    payload: dict[str, Any] = Field(
        default_factory=dict,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=128,
    )


class TelegramEventProcessingResult(ResponseSchema):
    """Result of processing an incoming Telegram event."""

    event_id: str

    event_type: TelegramEventTypeSchema

    status: TelegramEventStatusSchema

    matched_forwarding_rules: list[int] = Field(
        default_factory=list,
    )

    queued_message_ids: list[int] = Field(
        default_factory=list,
    )

    ignored_reason: str | None = None

    error_message: str | None = None

    processed_at: datetime | None = None
