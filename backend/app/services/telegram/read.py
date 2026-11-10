"""
Telegram message read-acknowledgement service.

Supports:
- Marking chat messages as read.
- Marking messages up to a specified message ID as read.
- Clearing unread mention notifications.
- Clearing unread reaction notifications.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatIdInvalidError,
    FloodWaitError,
    MessageIdInvalidError,
    PeerIdInvalidError,
)

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramReadResult:
    """Result of a Telegram read-acknowledgement operation."""

    account_id: int
    chat_id: int
    max_message_id: int | None
    successful: bool
    mentions_cleared: bool
    reactions_cleared: bool


class TelegramReadService:
    """Manage Telegram message read acknowledgements."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def mark_read(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        *,
        max_message_id: int | None = None,
        clear_mentions: bool = False,
        clear_reactions: bool = False,
    ) -> TelegramReadResult:
        """
        Mark messages as read in a Telegram chat.

        When max_message_id is omitted, Telegram determines the
        applicable read boundary according to the chat and API.

        Mention and reaction notification clearing are optional.
        """
        self._validate_identifiers(
            account_id,
            chat_id,
            max_message_id,
        )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        try:
            successful = await client.send_read_acknowledge(
                entity,
                max_id=max_message_id,
                clear_mentions=clear_mentions,
                clear_reactions=clear_reactions,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_read_acknowledgement_flood_wait",
                account_id=account_id,
                chat_id=chat_id,
                max_message_id=max_message_id,
            )
            raise

        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
            MessageIdInvalidError,
            PeerIdInvalidError,
        ):
            logger.exception(
                "telegram_read_acknowledgement_failed",
                account_id=account_id,
                chat_id=chat_id,
                max_message_id=max_message_id,
            )
            raise

        result = TelegramReadResult(
            account_id=account_id,
            chat_id=chat_id,
            max_message_id=max_message_id,
            successful=bool(successful),
            mentions_cleared=clear_mentions,
            reactions_cleared=clear_reactions,
        )

        logger.info(
            "telegram_read_acknowledgement_completed",
            account_id=account_id,
            chat_id=chat_id,
            max_message_id=max_message_id,
            successful=result.successful,
            mentions_cleared=clear_mentions,
            reactions_cleared=clear_reactions,
        )

        return result

    async def mark_message_read(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
    ) -> TelegramReadResult:
        """Mark messages up to a specified message ID as read."""
        if message_id <= 0:
            raise ValueError("message_id must be positive.")

        return await self.mark_read(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            chat_id=chat_id,
            max_message_id=message_id,
        )

    async def mark_chat_read(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> TelegramReadResult:
        """Mark the chat's available messages as read."""
        return await self.mark_read(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            chat_id=chat_id,
        )

    async def clear_mentions(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> TelegramReadResult:
        """Clear unread mention notifications in a chat."""
        return await self.mark_read(
            account_id=account_id,
            api_id=api_id,
            chat_id=chat_id,
            clear_mentions=True,
        )

    async def clear_reactions(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> TelegramReadResult:
        """Clear unread reaction notifications in a chat."""
        return await self.mark_read(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            chat_id=chat_id,
            clear_reactions=True,
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
    def _validate_identifiers(
        account_id: int,
        chat_id: int,
        max_message_id: int | None,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

        if (
            max_message_id is not None
            and max_message_id <= 0
        ):
            raise ValueError(
                "max_message_id must be positive."
            )
