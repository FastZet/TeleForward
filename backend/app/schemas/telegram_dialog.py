
"""
TeleForward Telegram dialog schemas.

Defines:
- Telegram dialog synchronization requests.
- Dialog discovery and listing filters.
- Dialog information returned by Telegram.
- Dialog synchronization status and results.
- Chat selection requests.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import RequestSchema, ResponseSchema


class TelegramDialogTypeSchema(StrEnum):
    """Telegram dialog categories."""

    PRIVATE = "private"
    BOT = "bot"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class TelegramDialogSyncStatusSchema(StrEnum):
    """Telegram dialog synchronization states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TelegramDialogSyncRequest(RequestSchema):
    """Request to synchronize an account's Telegram dialogs."""

    account_id: int = Field(
        gt=0,
    )

    force_refresh: bool = False

    include_archived: bool = True

    include_left_chats: bool = False

    dialog_types: list[TelegramDialogTypeSchema] | None = Field(
        default=None,
        max_length=5,
    )

    @model_validator(mode="after")
    def validate_dialog_types(self):
        """Reject duplicate dialog types."""

        if self.dialog_types is not None:
            if len(self.dialog_types) != len(set(self.dialog_types)):
                raise ValueError(
                    "Dialog types must not contain duplicates"
                )

        return self


class TelegramDialogListQuery(RequestSchema):
    """Filters for listing synchronized Telegram dialogs."""

    account_id: int = Field(
        gt=0,
    )

    dialog_type: TelegramDialogTypeSchema | None = None

    search: str | None = Field(
        default=None,
        max_length=500,
    )

    archived: bool | None = None

    pinned: bool | None = None

    unread_only: bool = False

    include_left_chats: bool = False

    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
    )

    offset: int = Field(
        default=0,
        ge=0,
    )


class TelegramDialogResponse(ResponseSchema):
    """A Telegram dialog discovered for an account."""

    id: int

    account_id: int

    telegram_chat_id: int

    dialog_type: TelegramDialogTypeSchema

    title: str

    username: str | None = None

    phone: str | None = None

    first_name: str | None = None

    last_name: str | None = None

    is_verified: bool = False

    is_scam: bool = False

    is_fake: bool = False

    is_archived: bool = False

    is_pinned: bool = False

    is_left: bool = False

    is_forum: bool = False

    unread_count: int = Field(
        default=0,
        ge=0,
    )

    unread_mentions_count: int = Field(
        default=0,
        ge=0,
    )

    last_message_id: int | None = Field(
        default=None,
        gt=0,
    )

    last_message_date: datetime | None = None

    synchronized_at: datetime | None = None

    created_at: datetime

    updated_at: datetime


class TelegramDialogSyncResponse(ResponseSchema):
    """Result of synchronizing Telegram dialogs."""

    id: int

    account_id: int

    status: TelegramDialogSyncStatusSchema

    total_discovered: int = Field(
        default=0,
        ge=0,
    )

    total_created: int = Field(
        default=0,
        ge=0,
    )

    total_updated: int = Field(
        default=0,
        ge=0,
    )

    total_skipped: int = Field(
        default=0,
        ge=0,
    )

    error_message: str | None = Field(
        default=None,
        max_length=2000,
    )

    started_at: datetime | None = None

    completed_at: datetime | None = None


class TelegramDialogSelectionRequest(RequestSchema):
    """Select Telegram dialogs for a forwarding operation."""

    account_id: int = Field(
        gt=0,
    )

    chat_ids: list[int] = Field(
        min_length=1,
        max_length=500,
    )

    @model_validator(mode="after")
    def validate_chat_ids(self):
        """Reject duplicate Telegram chat identifiers."""

        if len(self.chat_ids) != len(set(self.chat_ids)):
            raise ValueError(
                "Chat IDs must not contain duplicates"
            )

        return self


class TelegramDialogSelectionResponse(ResponseSchema):
    """Result of validating a dialog selection."""

    account_id: int

    selected_chat_ids: list[int] = Field(
        default_factory=list,
    )

    accepted_count: int = Field(
        default=0,
        ge=0,
    )

    rejected_chat_ids: list[int] = Field(
        default_factory=list,
    )

    rejected_count: int = Field(
        default=0,
        ge=0,
    )
