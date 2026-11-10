"""
Telegram message-search service.

Supports:
- Searching messages by text.
- Filtering by sender.
- Filtering by Telegram media type.
- Restricting searches using message-ID boundaries.
- Bounded result retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatIdInvalidError,
    FloodWaitError,
    PeerIdInvalidError,
)
from telethon.tl.custom.message import Message

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 500
MAX_SEARCH_QUERY_LENGTH = 256


@dataclass(frozen=True, slots=True)
class TelegramSearchResult:
    """A normalised Telegram message search result."""

    message_id: int
    chat_id: int
    sender_id: int | None
    text: str
    date: datetime
    has_media: bool
    media_type: str | None
    grouped_id: int | None
    reply_to_message_id: int | None


@dataclass(frozen=True, slots=True)
class TelegramSearchResponse:
    """Response containing Telegram search results."""

    account_id: int
    chat_id: int
    query: str | None
    results: tuple[TelegramSearchResult, ...]
    count: int
    limit: int
    has_more: bool


class TelegramSearchService:
    """Search Telegram messages."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def search_messages(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        *,
        query: str | None = None,
        from_user: int | str | None = None,
        media_filter: Any | None = None,
        min_message_id: int | None = None,
        max_message_id: int | None = None,
        offset_id: int = 0,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> TelegramSearchResponse:
        """
        Search messages in a Telegram chat.

        query:
            Optional Telegram text-search query.

        from_user:
            Optional sender user ID, username, or entity reference.

        media_filter:
            Optional Telethon InputMessagesFilter instance.

        min_message_id / max_message_id:
            Optional message-ID boundaries.

        offset_id:
            Telegram pagination cursor. Results continue relative
            to this message ID.

        limit:
            Maximum number of returned messages.
        """
        self._validate_parameters(
            account_id=account_id,
            chat_id=chat_id,
            query=query,
            min_message_id=min_message_id,
            max_message_id=max_message_id,
            offset_id=offset_id,
            limit=limit,
        )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        sender = None

        if from_user is not None:
            sender = await client.get_input_entity(from_user)

        try:
            messages = await client.get_messages(
                entity,
                search=query,
                from_user=sender,
                filter=media_filter,
                min_id=min_message_id or 0,
                max_id=max_message_id or 0,
                offset_id=offset_id,
                limit=limit + 1,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_message_search_flood_wait",
                account_id=account_id,
                chat_id=chat_id,
            )
            raise

        except (
            ChannelPrivateError,
            ChatIdInvalidError,
            PeerIdInvalidError,
        ):
            logger.exception(
                "telegram_message_search_failed",
                account_id=account_id,
                chat_id=chat_id,
            )
            raise

        if not isinstance(messages, list):
            messages = [messages]

        valid_messages = [
            message
            for message in messages
            if isinstance(message, Message)
        ]

        has_more = len(valid_messages) > limit
        valid_messages = valid_messages[:limit]

        results = tuple(
            self._normalise_message(message)
            for message in valid_messages
        )

        logger.info(
            "telegram_message_search_completed",
            account_id=account_id,
            chat_id=chat_id,
            result_count=len(results),
            has_more=has_more,
        )

        return TelegramSearchResponse(
            account_id=account_id,
            chat_id=chat_id,
            query=query,
            results=results,
            count=len(results),
            limit=limit,
            has_more=has_more,
        )

    async def search_text(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        query: str,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
        offset_id: int = 0,
    ) -> TelegramSearchResponse:
        """Search messages using a text query."""
        if not query or not query.strip():
            raise ValueError("A non-empty search query is required.")

        return await self.search_messages(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            chat_id=chat_id,
            query=query.strip(),
            limit=limit,
            offset_id=offset_id,
        )

    async def search_from_user(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        user_id: int | str,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
        offset_id: int = 0,
    ) -> TelegramSearchResponse:
        """Search messages sent by a specific user."""
        return await self.search_messages(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            chat_id=chat_id,
            from_user=user_id,
            limit=limit,
            offset_id=offset_id,
        )

    @staticmethod
    def _normalise_message(
        message: Message,
    ) -> TelegramSearchResult:
        """Convert a Telethon message into a service result."""
        media = message.media

        media_type = None

        if message.photo:
            media_type = "photo"
        elif message.video:
            media_type = "video"
        elif message.audio:
            media_type = "audio"
        elif message.voice:
            media_type = "voice"
        elif message.video_note:
            media_type = "video_note"
        elif message.document:
            media_type = "document"
        elif media is not None:
            media_type = type(media).__name__

        reply_to = getattr(message, "reply_to", None)

        return TelegramSearchResult(
            message_id=message.id,
            chat_id=message.chat_id or 0,
            sender_id=message.sender_id,
            text=message.message or "",
            date=message.date,
            has_media=media is not None,
            media_type=media_type,
            grouped_id=message.grouped_id,
            reply_to_message_id=(
                getattr(reply_to, "reply_to_msg_id", None)
                if reply_to is not None
                else None
            ),
        )

    async def _get_authorized_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Retrieve an authorised Telegram client."""
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        client = await self.client_manager.get_client(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            connect=True,
        )

        if not await client.is_user_authorized():
            raise PermissionError(
                "The Telegram account is not authorised."
            )

        return client

    @staticmethod
    def _validate_parameters(
        *,
        account_id: int,
        chat_id: int,
        query: str | None,
        min_message_id: int | None,
        max_message_id: int | None,
        offset_id: int,
        limit: int,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

        if query is not None:
            if not query.strip():
                raise ValueError("Search query cannot be empty.")

            if len(query) > MAX_SEARCH_QUERY_LENGTH:
                raise ValueError(
                    f"Search query cannot exceed "
                    f"{MAX_SEARCH_QUERY_LENGTH} characters."
                )

        if min_message_id is not None and min_message_id < 0:
            raise ValueError("min_message_id cannot be negative.")

        if max_message_id is not None and max_message_id < 0:
            raise ValueError("max_message_id cannot be negative.")

        if (
            min_message_id is not None
            and max_message_id is not None
            and min_message_id >= max_message_id
        ):
            raise ValueError(
                "min_message_id must be smaller than max_message_id."
            )

        if offset_id < 0:
            raise ValueError("offset_id cannot be negative.")

        if not 1 <= limit <= MAX_SEARCH_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {MAX_SEARCH_LIMIT}."
            )
