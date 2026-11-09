
"""
TeleForward Telegram message schemas.

Defines:
- Telegram message content and metadata.
- Message formatting entities.
- Reply and grouped-media references.
- Message retrieval requests and filters.
- Message response representations.

Telegram message IDs are scoped to their chat.
Chat IDs may be negative.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class TelegramMessageEntityTypeSchema(StrEnum):
    """Supported Telegram message formatting entities."""

    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    STRIKETHROUGH = "strikethrough"
    CODE = "code"
    PRE = "pre"
    BLOCKQUOTE = "blockquote"
    TEXT_URL = "text_url"
    URL = "url"
    MENTION = "mention"
    HASHTAG = "hashtag"
    CASHTAG = "cashtag"
    BOT_COMMAND = "bot_command"
    EMAIL = "email"
    PHONE = "phone"
    CUSTOM_EMOJI = "custom_emoji"
    SPOILER = "spoiler"
    UNKNOWN = "unknown"


class TelegramMessageContentTypeSchema(StrEnum):
    """Telegram message content categories."""

    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    ANIMATION = "animation"
    STICKER = "sticker"
    CONTACT = "contact"
    LOCATION = "location"
    POLL = "poll"
    ALBUM = "album"
    OTHER = "other"


class TelegramMessageEntitySchema(RequestSchema):
    """Formatting or semantic entity within message text."""

    entity_type: TelegramMessageEntityTypeSchema

    offset: int = Field(
        ge=0,
    )

    length: int = Field(
        gt=0,
    )

    url: str | None = Field(
        default=None,
        max_length=4096,
    )

    language: str | None = Field(
        default=None,
        max_length=100,
    )

    custom_emoji_id: int | None = None


class TelegramMessageResponse(ResponseSchema):
    """Telegram message information."""

    id: int

    account_id: int

    chat_id: int

    telegram_message_id: int

    sender_id: int | None = None

    reply_to_message_id: int | None = None

    grouped_id: int | None = None

    content_type: TelegramMessageContentTypeSchema

    text: str | None = None

    caption: str | None = None

    entities: list[TelegramMessageEntitySchema] = Field(
        default_factory=list,
    )

    has_media: bool = False

    media: list[dict] = Field(
        default_factory=list,
    )

    views: int | None = Field(
        default=None,
        ge=0,
    )

    forwards: int | None = Field(
        default=None,
        ge=0,
    )

    is_outgoing: bool = False

    is_edited: bool = False

    is_pinned: bool = False

    is_deleted: bool = False

    message_date: datetime

    edited_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


class TelegramMessageListQuery(RequestSchema):
    """Filter messages from a Telegram chat."""

    account_id: int = Field(
        gt=0,
    )

    chat_id: int

    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    before_message_id: int | None = Field(
        default=None,
        gt=0,
    )

    after_message_id: int | None = Field(
        default=None,
        gt=0,
    )

    search: str | None = Field(
        default=None,
        max_length=500,
    )

    content_type: TelegramMessageContentTypeSchema | None = None

    has_media: bool | None = None

    @model_validator(mode="after")
    def validate_message_range(self):
        """Prevent contradictory message pagination boundaries."""

        if (
            self.before_message_id is not None
            and self.after_message_id is not None
        ):
            if self.before_message_id <= self.after_message_id:
                raise ValueError(
                    "before_message_id must be greater than "
                    "after_message_id"
                )

        return self


class TelegramMessageGetRequest(RequestSchema):
    """Retrieve a specific Telegram message."""

    account_id: int = Field(
        gt=0,
    )

    chat_id: int

    message_id: int = Field(
        gt=0,
    )


class TelegramMessageHistoryRequest(RequestSchema):
    """Retrieve historical messages from a Telegram chat."""

    account_id: int = Field(
        gt=0,
    )

    chat_id: int

    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    offset_id: int | None = Field(
        default=None,
        gt=0,
    )

    reverse: bool = False

    min_date: datetime | None = None

    max_date: datetime | None = None

    @model_validator(mode="after")
    def validate_date_range(self):
        """Validate historical retrieval date boundaries."""

        if self.min_date is not None and self.max_date is not None:
            if self.max_date < self.min_date:
                raise ValueError(
                    "max_date must be later than or equal to min_date"
                )

            if (
                self.min_date.tzinfo is None
                or self.max_date.tzinfo is None
            ):
                raise ValueError(
                    "History date boundaries must be timezone-aware"
                )

        return self


class TelegramMessageHistoryResponse(ResponseSchema):
    """Result of retrieving Telegram message history."""

    account_id: int

    chat_id: int

    messages: list[TelegramMessageResponse] = Field(
        default_factory=list,
    )

    total_retrieved: int = Field(
        ge=0,
    )

    has_more: bool = False

    next_offset_id: int | None = None
