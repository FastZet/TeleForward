"""
Telegram forwarding service.

Executes message forwarding operations through Telethon.

This service handles Telegram API communication only. Rule evaluation,
filtering, scheduling, persistent queue management, and delivery
deduplication belong to the higher-level forwarding services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

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

DEFAULT_BATCH_SIZE = 100
MAX_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class TelegramForwardResult:
    """Result of a Telegram forwarding operation."""

    account_id: int
    source_chat_id: int
    destination_chat_id: int
    source_message_ids: tuple[int, ...]
    destination_message_ids: tuple[int, ...]
    successful: bool


class TelegramForwardingService:
    """Execute Telegram message forwarding operations."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def forward_message(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        source_chat_id: int,
        destination_chat_id: int,
        message_id: int,
        *,
        silent: bool = False,
        drop_author: bool = False,
        drop_media_captions: bool = False,
    ) -> TelegramForwardResult:
        """Forward a single Telegram message."""
        results = await self.forward_messages(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            source_chat_id=source_chat_id,
            destination_chat_id=destination_chat_id,
            message_ids=[message_id],
            silent=silent,
            drop_author=drop_author,
            drop_media_captions=drop_media_captions,
        )

        return results[0]

    async def forward_messages(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        source_chat_id: int,
        destination_chat_id: int,
        message_ids: Sequence[int],
        *,
        silent: bool = False,
        drop_author: bool = False,
        drop_media_captions: bool = False,
    ) -> list[TelegramForwardResult]:
        """
        Forward one or more messages between Telegram chats.

        Message IDs are processed in bounded batches. Each batch is
        submitted to Telegram as one forwarding operation, preserving
        the ordering of the supplied message IDs.

        Note:
            Telegram controls the final destination message IDs and
            may return fewer messages than requested.
        """
        self._validate_identifiers(
            account_id,
            source_chat_id,
            destination_chat_id,
        )

        self._validate_message_ids(message_ids)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        source = await client.get_input_entity(source_chat_id)
        destination = await client.get_input_entity(
            destination_chat_id
        )

        results: list[TelegramForwardResult] = []

        for start in range(0, len(message_ids), MAX_BATCH_SIZE):
            batch = list(
                message_ids[start:start + MAX_BATCH_SIZE]
            )

            try:
                forwarded = await client.forward_messages(
                    entity=destination,
                    messages=batch,
                    from_peer=source,
                    silent=silent,
                    drop_author=drop_author,
                    drop_media_captions=drop_media_captions,
                )

            except FloodWaitError:
                logger.warning(
                    "telegram_forward_flood_wait",
                    account_id=account_id,
                    source_chat_id=source_chat_id,
                    destination_chat_id=destination_chat_id,
                    batch_size=len(batch),
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
                    "telegram_forward_failed",
                    account_id=account_id,
                    source_chat_id=source_chat_id,
                    destination_chat_id=destination_chat_id,
                    message_ids=batch,
                )
                raise

            forwarded_messages = self._normalise_messages(
                forwarded
            )

            destination_ids = tuple(
                message.id
                for message in forwarded_messages
                if getattr(message, "id", None) is not None
            )

            if len(destination_ids) != len(batch):
                logger.warning(
                    "telegram_forward_result_count_mismatch",
                    account_id=account_id,
                    source_chat_id=source_chat_id,
                    destination_chat_id=destination_chat_id,
                    requested_count=len(batch),
                    returned_count=len(destination_ids),
                )

            results.append(
                TelegramForwardResult(
                    account_id=account_id,
                    source_chat_id=source_chat_id,
                    destination_chat_id=destination_chat_id,
                    source_message_ids=tuple(batch),
                    destination_message_ids=destination_ids,
                    successful=len(destination_ids) == len(batch),
                )
            )

            logger.info(
                "telegram_messages_forwarded",
                account_id=account_id,
                source_chat_id=source_chat_id,
                destination_chat_id=destination_chat_id,
                source_message_count=len(batch),
                destination_message_count=len(destination_ids),
            )

        return results

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
    def _normalise_messages(
        messages: object,
    ) -> list:
        """Normalise Telethon's single-message and batch responses."""
        if messages is None:
            return []

        if isinstance(messages, (list, tuple)):
            return [
                message
                for message in messages
                if message is not None
            ]

        return [messages]

    @staticmethod
    def _validate_identifiers(
        account_id: int,
        source_chat_id: int,
        destination_chat_id: int,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if source_chat_id == 0:
            raise ValueError("source_chat_id cannot be zero.")

        if destination_chat_id == 0:
            raise ValueError("destination_chat_id cannot be zero.")

    @staticmethod
    def _validate_message_ids(
        message_ids: Sequence[int],
    ) -> None:
        if not message_ids:
            raise ValueError("At least one message ID is required.")

        if len(message_ids) > 10_000:
            raise ValueError(
                "A maximum of 10,000 message IDs can be submitted."
            )

        if any(message_id <= 0 for message_id in message_ids):
            raise ValueError("All message IDs must be positive.")

        if len(set(message_ids)) != len(message_ids):
            raise ValueError("Duplicate message IDs are not allowed.")
