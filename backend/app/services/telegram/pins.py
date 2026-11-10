"""
Telegram pinned-message service.

Provides pinning, unpinning, and retrieval of pinned messages
through Telethon.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from telethon import TelegramClient, functions, types
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatIdInvalidError,
    MessageIdInvalidError,
    MessageNotModifiedError,
)

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

DEFAULT_PINNED_MESSAGE_LIMIT = 50
MAX_PINNED_MESSAGE_LIMIT = 200


@dataclass(frozen=True, slots=True)
class TelegramPinnedMessage:
    """Normalised information about a pinned Telegram message."""

    message_id: int
    chat_id: int
    date: datetime | None
    text: str | None
    sender_id: int | None
    grouped_id: int | None
    has_media: bool


class TelegramPinsService:
    """Manage pinned messages in Telegram chats and channels."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def pin_message(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
        *,
        silent: bool = False,
    ) -> None:
        """
        Pin a message in a Telegram chat or channel.

        The Telegram account must have permission to pin messages.
        """
        self._validate_identifiers(
            account_id,
            chat_id,
            message_id,
        )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        try:
            await client(
                functions.messages.UpdatePinnedMessageRequest(
                    peer=entity,
                    id=message_id,
                    silent=silent,
                )
            )
        except MessageNotModifiedError:
            logger.debug(
                "telegram_message_already_pinned",
                account_id=account_id,
                chat_id=chat_id,
                message_id=message_id,
            )
            return
        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
            MessageIdInvalidError,
        ):
            raise

        logger.info(
            "telegram_message_pinned",
            account_id=account_id,
            chat_id=chat_id,
            message_id=message_id,
        )

    async def unpin_message(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
    ) -> None:
        """Unpin a specific message."""
        self._validate_identifiers(
            account_id,
            chat_id,
            message_id,
        )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        try:
            await client(
                functions.messages.UpdatePinnedMessageRequest(
                    peer=entity,
                    id=message_id,
                    unpin=True,
                )
            )
        except MessageNotModifiedError:
            logger.debug(
                "telegram_message_already_unpinned",
                account_id=account_id,
                chat_id=chat_id,
                message_id=message_id,
            )
            return
        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
            MessageIdInvalidError,
        ):
            raise

        logger.info(
            "telegram_message_unpinned",
            account_id=account_id,
            chat_id=chat_id,
            message_id=message_id,
        )

    async def unpin_all_messages(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> None:
        """Remove all pinned messages from a Telegram chat or channel."""
        self._validate_chat_id(chat_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        try:
            await client(
                functions.messages.UnpinAllMessagesRequest(
                    peer=entity,
                )
            )
        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
        ):
            raise

        logger.info(
            "telegram_all_messages_unpinned",
            account_id=account_id,
            chat_id=chat_id,
        )

    async def list_pinned_messages(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        *,
        limit: int = DEFAULT_PINNED_MESSAGE_LIMIT,
    ) -> list[TelegramPinnedMessage]:
        """
        Retrieve pinned messages from a Telegram chat or channel.

        Results are returned newest first.
        """
        self._validate_chat_id(chat_id)

        if not 1 <= limit <= MAX_PINNED_MESSAGE_LIMIT:
            raise ValueError(
                f"limit must be between 1 and "
                f"{MAX_PINNED_MESSAGE_LIMIT}."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            messages = client.iter_messages(
                chat_id,
                limit=limit,
                filter=types.InputMessagesFilterPinned(),
            )

            pinned_messages: list[TelegramPinnedMessage] = []

            async for message in messages:
                if message is None:
                    continue

                pinned_messages.append(
                    self._normalise_message(
                        message=message,
                        chat_id=chat_id,
                    )
                )

            return pinned_messages

        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
        ):
            raise

    async def is_message_pinned(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
    ) -> bool:
        """Check whether a specific message is currently pinned."""
        self._validate_identifiers(
            account_id,
            chat_id,
            message_id,
        )

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
        ):
            raise

        if message is None or isinstance(message, list):
            return False

        return bool(getattr(message, "pinned", False))

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
    def _normalise_message(
        message: Any,
        chat_id: int,
    ) -> TelegramPinnedMessage:
        """Convert a Telethon message into a stable representation."""
        return TelegramPinnedMessage(
            message_id=message.id,
            chat_id=chat_id,
            date=getattr(message, "date", None),
            text=getattr(message, "message", None),
            sender_id=getattr(message, "sender_id", None),
            grouped_id=getattr(message, "grouped_id", None),
            has_media=getattr(message, "media", None) is not None,
        )

    @staticmethod
    def _validate_chat_id(chat_id: int) -> None:
        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

    @classmethod
    def _validate_identifiers(
        cls,
        account_id: int,
        chat_id: int,
        message_id: int,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        cls._validate_chat_id(chat_id)

        if message_id <= 0:
            raise ValueError("message_id must be positive.")
