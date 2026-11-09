"""
Telegram message retrieval service.

Provides read-only access to Telegram messages through Telethon.
Message persistence, forwarding, editing, and deletion synchronisation
are handled by their respective application services.
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
    MessageIdInvalidError,
)
from telethon.tl.custom.message import Message

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramMessageInfo:
    """Normalised representation of a Telegram message."""

    message_id: int
    chat_id: int
    sender_id: int | None
    text: str
    date: datetime | None
    edit_date: datetime | None
    reply_to_message_id: int | None
    grouped_id: int | None
    views: int | None
    forwards: int | None
    has_media: bool
    media_type: str | None
    is_outgoing: bool
    is_forwarded: bool
    is_pinned: bool
    is_reply: bool


@dataclass(frozen=True, slots=True)
class TelegramMessagePage:
    """Paginated Telegram message history."""

    messages: list[TelegramMessageInfo]
    next_offset_id: int | None
    has_more: bool


class TelegramMessageService:
    """Retrieve Telegram messages and message history."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def get_message(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
    ) -> TelegramMessageInfo | None:
        """Retrieve one message by Telegram chat and message IDs."""
        self._validate_identifiers(account_id, chat_id, message_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            message = await client.get_messages(
                chat_id,
                ids=message_id,
            )
        except (
            ChannelPrivateError,
            ChatIdInvalidError,
            MessageIdInvalidError,
        ):
            raise

        if message is None or isinstance(message, list):
            return None

        return self._normalise_message(message, chat_id)

    async def get_history(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        *,
        limit: int = 100,
        offset_id: int = 0,
        min_id: int = 0,
        max_id: int = 0,
        reverse: bool = False,
    ) -> TelegramMessagePage:
        """
        Retrieve a page of messages from a Telegram chat.

        Args:
            account_id: Internal TeleForward account ID.
            api_id: Telegram application API ID.
            api_hash: Telegram application API hash.
            chat_id: Telegram chat ID.
            limit: Number of messages requested.
            offset_id: Telegram message ID used as pagination offset.
            min_id: Exclude messages with IDs at or below this value.
            max_id: Exclude messages with IDs at or above this value.
            reverse: Retrieve messages in ascending chronological order.

        Returns:
            A page of normalised messages and pagination metadata.
        """
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")

        if offset_id < 0 or min_id < 0 or max_id < 0:
            raise ValueError("Message offsets cannot be negative.")

        if min_id and max_id and min_id >= max_id:
            raise ValueError("min_id must be smaller than max_id.")

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        messages: list[TelegramMessageInfo] = []

        async for message in client.iter_messages(
            chat_id,
            limit=limit + 1,
            offset_id=offset_id,
            min_id=min_id,
            max_id=max_id,
            reverse=reverse,
        ):
            if message.id is None:
                continue

            messages.append(
                self._normalise_message(message, chat_id)
            )

        has_more = len(messages) > limit
        messages = messages[:limit]

        next_offset_id = (
            messages[-1].message_id
            if messages and has_more
            else None
        )

        logger.info(
            "telegram_message_history_retrieved",
            account_id=account_id,
            chat_id=chat_id,
            message_count=len(messages),
            has_more=has_more,
        )

        return TelegramMessagePage(
            messages=messages,
            next_offset_id=next_offset_id,
            has_more=has_more,
        )

    async def get_latest_message(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> TelegramMessageInfo | None:
        """Retrieve the latest available message from a chat."""
        self._validate_identifiers(account_id, chat_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        messages = await client.get_messages(chat_id, limit=1)

        if not messages:
            return None

        message = messages[0]

        return self._normalise_message(message, chat_id)

    async def _get_authorized_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Retrieve a connected and authorised Telegram client."""
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
    def _validate_identifiers(
        account_id: int,
        chat_id: int,
        message_id: int | None = None,
    ) -> None:
        """Validate Telegram and internal account identifiers."""
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

        if message_id is not None and message_id <= 0:
            raise ValueError("message_id must be positive.")

    @staticmethod
    def _get_media_type(message: Message) -> str | None:
        """Return a normalised media category."""
        media = message.media

        if media is None:
            return None

        media_name = type(media).__name__

        if media_name == "MessageMediaPhoto":
            return "photo"

        if media_name == "MessageMediaDocument":
            document = getattr(media, "document", None)

            if document is not None:
                attributes = getattr(document, "attributes", [])

                for attribute in attributes:
                    attribute_name = type(attribute).__name__

                    if attribute_name == "DocumentAttributeVideo":
                        return "video"

                    if attribute_name == "DocumentAttributeAudio":
                        if getattr(attribute, "voice", False):
                            return "voice"
                        return "audio"

                    if attribute_name == "DocumentAttributeSticker":
                        return "sticker"

                    if attribute_name == "DocumentAttributeAnimated":
                        return "animation"

            return "document"

        if media_name == "MessageMediaGeo":
            return "location"

        if media_name == "MessageMediaContact":
            return "contact"

        if media_name == "MessageMediaPoll":
            return "poll"

        if media_name == "MessageMediaWebPage":
            return "webpage"

        return "other"

    @classmethod
    def _normalise_message(
        cls,
        message: Message,
        chat_id: int,
    ) -> TelegramMessageInfo:
        """Convert a Telethon message into a normalised representation."""
        reply_to = getattr(message, "reply_to", None)

        reply_to_message_id = (
            getattr(reply_to, "reply_to_msg_id", None)
            if reply_to is not None
            else None
        )

        return TelegramMessageInfo(
            message_id=message.id,
            chat_id=chat_id,
            sender_id=message.sender_id,
            text=message.message or "",
            date=message.date,
            edit_date=message.edit_date,
            reply_to_message_id=reply_to_message_id,
            grouped_id=message.grouped_id,
            views=message.views,
            forwards=message.forwards,
            has_media=message.media is not None,
            media_type=cls._get_media_type(message),
            is_outgoing=bool(message.out),
            is_forwarded=message.forward is not None,
            is_pinned=bool(message.pinned),
            is_reply=reply_to_message_id is not None,
        )
