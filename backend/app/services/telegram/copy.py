"""
Telegram message-copying service.

Copies Telegram message content by re-sending text and media rather
than using Telegram's native forwarding operation.

This service handles individual messages and bounded batches.
Grouped media albums are intentionally handled separately.
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
from telethon.tl.custom.message import Message

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

MAX_COPY_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class TelegramCopyResult:
    """Result of a Telegram message-copy operation."""

    account_id: int
    source_chat_id: int
    destination_chat_id: int
    source_message_ids: tuple[int, ...]
    destination_message_ids: tuple[int, ...]
    successful: bool


class TelegramCopyService:
    """Copy Telegram messages without preserving forwarding attribution."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def copy_message(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        source_chat_id: int,
        destination_chat_id: int,
        message_id: int,
        *,
        silent: bool = False,
        formatting_entities: bool = True,
    ) -> TelegramCopyResult:
        """Copy a single Telegram message."""
        results = await self.copy_messages(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            source_chat_id=source_chat_id,
            destination_chat_id=destination_chat_id,
            message_ids=[message_id],
            silent=silent,
            formatting_entities=formatting_entities,
        )

        return results[0]

    async def copy_messages(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        source_chat_id: int,
        destination_chat_id: int,
        message_ids: Sequence[int],
        *,
        silent: bool = False,
        formatting_entities: bool = True,
    ) -> list[TelegramCopyResult]:
        """
        Copy messages by re-sending their content.

        Messages are processed individually to preserve their order.
        Each source message produces an independent result.

        Unsupported service messages are skipped and reported as
        unsuccessful results.
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

        results: list[TelegramCopyResult] = []

        for start in range(
            0,
            len(message_ids),
            MAX_COPY_BATCH_SIZE,
        ):
            batch = list(
                message_ids[start:start + MAX_COPY_BATCH_SIZE]
            )

            messages = await client.get_messages(
                source,
                ids=batch,
            )

            if not isinstance(messages, list):
                messages = [messages]

            message_by_id = {
                message.id: message
                for message in messages
                if isinstance(message, Message)
            }

            for message_id in batch:
                message = message_by_id.get(message_id)

                if message is None:
                    results.append(
                        self._failed_result(
                            account_id,
                            source_chat_id,
                            destination_chat_id,
                            message_id,
                        )
                    )
                    continue

                if getattr(message, "action", None) is not None:
                    logger.warning(
                        "telegram_service_message_copy_skipped",
                        account_id=account_id,
                        source_chat_id=source_chat_id,
                        message_id=message_id,
                    )

                    results.append(
                        self._failed_result(
                            account_id,
                            source_chat_id,
                            destination_chat_id,
                            message_id,
                        )
                    )
                    continue

                try:
                    copied = await self._copy_single_message(
                        client=client,
                        destination=destination,
                        message=message,
                        silent=silent,
                        formatting_entities=formatting_entities,
                    )

                except FloodWaitError:
                    logger.warning(
                        "telegram_copy_flood_wait",
                        account_id=account_id,
                        source_chat_id=source_chat_id,
                        destination_chat_id=destination_chat_id,
                        message_id=message_id,
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
                        "telegram_message_copy_failed",
                        account_id=account_id,
                        message_id=message_id,
                    )
                    raise

                if copied is None:
                    results.append(
                        self._failed_result(
                            account_id,
                            source_chat_id,
                            destination_chat_id,
                            message_id,
                        )
                    )
                    continue

                results.append(
                    TelegramCopyResult(
                        account_id=account_id,
                        source_chat_id=source_chat_id,
                        destination_chat_id=destination_chat_id,
                        source_message_ids=(message_id,),
                        destination_message_ids=(copied.id,),
                        successful=True,
                    )
                )

                logger.info(
                    "telegram_message_copied",
                    account_id=account_id,
                    source_chat_id=source_chat_id,
                    destination_chat_id=destination_chat_id,
                    source_message_id=message_id,
                    destination_message_id=copied.id,
                )

        return results

    async def _copy_single_message(
        self,
        client: TelegramClient,
        destination: object,
        message: Message,
        *,
        silent: bool,
        formatting_entities: bool,
    ) -> Message | None:
        """Copy an individual text or media message."""
        text = message.message or ""

        entities = (
            message.entities
            if formatting_entities
            else None
        )

        if message.media is not None:
            return await client.send_file(
                destination,
                file=message.media,
                caption=text or None,
                formatting_entities=entities,
                silent=silent,
                parse_mode=None,
            )

        if text:
            return await client.send_message(
                destination,
                message=text,
                formatting_entities=entities,
                silent=silent,
                parse_mode=None,
            )

        # Empty messages without media cannot be meaningfully copied.
        return None

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
    def _failed_result(
        account_id: int,
        source_chat_id: int,
        destination_chat_id: int,
        message_id: int,
    ) -> TelegramCopyResult:
        """Construct an unsuccessful copy result."""
        return TelegramCopyResult(
            account_id=account_id,
            source_chat_id=source_chat_id,
            destination_chat_id=destination_chat_id,
            source_message_ids=(message_id,),
            destination_message_ids=(),
            successful=False,
        )

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
