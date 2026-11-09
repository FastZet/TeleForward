
"""
TeleForward Telegram chat schemas.

Defines:
- Chat synchronisation requests.
- Chat listing and filtering parameters.
- Chat update requests.
- Chat detail and summary responses.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class TelegramChatTypeSchema(StrEnum):
    """Supported Telegram chat categories."""

    PRIVATE = "private"
    BOT = "bot"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class ChatSyncRequest(RequestSchema):
    """Request to synchronise chats from a Telegram account."""

    account_id: int = Field(gt=0)

    include_archived: bool = False

    force_refresh: bool = False


class ChatUpdateRequest(RequestSchema):
    """Request to update locally maintained chat settings."""

    is_archived: bool | None = None


class ChatListQuery(RequestSchema):
    """Filtering parameters for chat listings."""

    account_id: int | None = Field(
        default=None,
        gt=0,
    )

    chat_type: TelegramChatTypeSchema | None = None

    search: str | None = Field(
        default=None,
        max_length=200,
    )

    is_accessible: bool | None = None

    is_archived: bool | None = None


class TelegramChatResponse(ResponseSchema):
    """Detailed Telegram chat representation."""

    id: int
    telegram_account_id: int
    telegram_chat_id: int

    title: str
    username: str | None = None

    chat_type: TelegramChatTypeSchema

    is_accessible: bool
    is_archived: bool
    is_forum: bool

    created_at: datetime
    updated_at: datetime


class TelegramChatSummaryResponse(ResponseSchema):
    """Compact chat representation for selectors and listings."""

    id: int
    telegram_account_id: int
    telegram_chat_id: int

    title: str
    username: str | None = None

    chat_type: TelegramChatTypeSchema
    is_accessible: bool
    is_archived: bool


class ChatSyncResponse(ResponseSchema):
    """Result of a Telegram chat synchronisation operation."""

    account_id: int

    total_discovered: int
    created: int
    updated: int
    unchanged: int
    inaccessible: int

    completed_at: datetime
