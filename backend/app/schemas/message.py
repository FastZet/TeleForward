
"""
TeleForward Telegram message schemas.

Defines:
- Message types and processing statuses.
- Media metadata.
- Message listing filters.
- Message detail and summary responses.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class MessageTypeSchema(StrEnum):
    """Supported Telegram message categories."""

    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    VOICE = "voice"
    DOCUMENT = "document"
    STICKER = "sticker"
    ANIMATION = "animation"
    VIDEO_NOTE = "video_note"
    CONTACT = "contact"
    LOCATION = "location"
    POLL = "poll"
    SERVICE = "service"
    UNKNOWN = "unknown"


class MessageProcessingStatusSchema(StrEnum):
    """Message processing lifecycle states."""

    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    SKIPPED = "skipped"
    FAILED = "failed"


class MediaMetadataSchema(ResponseSchema):
    """Structured metadata describing Telegram message media."""

    media_type: str | None = None
    mime_type: str | None = None

    file_name: str | None = None
    file_size: int | None = Field(default=None, ge=0)

    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)

    duration: float | None = Field(default=None, ge=0)

    thumbnail_available: bool = False

    attributes: dict[str, Any] = Field(
        default_factory=dict,
    )


class MessageListQuery(RequestSchema):
    """Filtering parameters for message listings."""

    account_id: int | None = Field(
        default=None,
        gt=0,
    )

    source_chat_id: int | None = Field(
        default=None,
        gt=0,
    )

    message_type: MessageTypeSchema | None = None

    processing_status: MessageProcessingStatusSchema | None = None

    sender_id: int | None = None

    search: str | None = Field(
        default=None,
        max_length=500,
    )

    date_from: datetime | None = None
    date_to: datetime | None = None

    has_media: bool | None = None


class TelegramMessageResponse(ResponseSchema):
    """Detailed locally stored Telegram message representation."""

    id: int

    telegram_account_id: int
    source_chat_id: int

    telegram_message_id: int
    grouped_id: int | None = None

    sender_id: int | None = None

    message_type: MessageTypeSchema

    text: str | None = None
    caption: str | None = None

    media_metadata: dict[str, Any] | None = None

    telegram_date: datetime
    edited_at: datetime | None = None

    processing_status: MessageProcessingStatusSchema

    content_hash: str | None = None
    retry_count: int

    last_error: str | None = None

    created_at: datetime
    updated_at: datetime


class TelegramMessageSummaryResponse(ResponseSchema):
    """Compact message representation for frontend listings."""

    id: int

    telegram_account_id: int
    source_chat_id: int

    telegram_message_id: int
    sender_id: int | None = None

    message_type: MessageTypeSchema

    text: str | None = None
    caption: str | None = None

    telegram_date: datetime

    processing_status: MessageProcessingStatusSchema


class MessageProcessingResponse(ResponseSchema):
    """Result of a message-processing operation."""

    message_id: int

    status: MessageProcessingStatusSchema

    forwarded: bool = False
    skipped: bool = False

    error: str | None = None
