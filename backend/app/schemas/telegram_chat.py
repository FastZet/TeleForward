
"""
TeleForward Telegram chat schemas.

Defines:
- Telegram chat metadata.
- Chat discovery and synchronisation requests.
- Chat filtering and listing.
- Chat selection.
- Synchronisation results.

Telegram chat IDs may be negative and must not be constrained
to positive integers.
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
    UNKNOWN = "unknown"


class TelegramChatSyncStatusSchema(StrEnum):
    """Chat synchronisation states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TelegramChatSyncRequest(RequestSchema):
    """Request synchronisation of chats for an account."""

    account_id: int = Field(
        gt=0,
    )

    force_refresh: bool = False

    include_archived: bool = True

    include_bots: bool = True

    include_groups: bool = True

    include_channels: bool = True

    include_private_chats: bool = True


class TelegramChatListQuery(RequestSchema):
    """Filter discovered Telegram chats."""

    account_id: int = Field(
        gt=0,
    )

    chat_type: TelegramChatTypeSchema | None = None

    search: str | None = Field(
        default=None,
        max_length=255,
    )

    archived: bool | None = None

    has_username: bool | None = None


class TelegramChatSelectionRequest(RequestSchema):
    """Select Telegram chats for a forwarding operation."""

    account_id: int = Field(
        gt=0,
    )

    chat_ids: list[int] = Field(
        min_length=1,
        max_length=500,
    )

    def validate_chat_ids(self):
        """Ensure chat identifiers are unique."""

        if len(set(self.chat_ids)) != len(self.chat_ids):
            raise ValueError(
                "chat_ids must not contain duplicates"
            )

        return self


class TelegramChatResponse(ResponseSchema):
    """Telegram chat information safe for API responses."""

    id: int

    account_id: int

    telegram_chat_id: int

    title: str

    username: str | None = None

    chat_type: TelegramChatTypeSchema

    description: str | None = None

    participant_count: int | None = Field(
        default=None,
        ge=0,
    )

    archived: bool = False

    is_verified: bool = False

    is_restricted: bool = False

    is_forum: bool = False

    last_message_id: int | None = None

    last_message_at: datetime | None = None

    last_synced_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


class TelegramChatListResponse(ResponseSchema):
    """Collection of discovered Telegram chats."""

    chats: list[TelegramChatResponse] = Field(
        default_factory=list,
    )

    total: int = Field(
        ge=0,
    )


class TelegramChatSyncResponse(ResponseSchema):
    """Result and progress of chat synchronisation."""

    account_id: int

    status: TelegramChatSyncStatusSchema

    total_chats: int | None = None

    discovered_chats: int = 0

    updated_chats: int = 0

    skipped_chats: int = 0

    failed_chats: int = 0

    started_at: datetime | None = None

    completed_at: datetime | None = None

    error_message: str | None = None
