"""
Telegram message-deletion service.

Supports:
- Deleting messages from the current account's history.
- Deleting messages for all participants where permitted.
- Batch deletion with bounded request sizes.
- Reporting individual deletion outcomes.
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

MAX_DELETE_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class TelegramDeleteResult:
    """Result of deleting Telegram messages."""

    account_id: int
    chat_id: int
    requested_message_ids: tuple[int, ...]
    deleted_message_ids: tuple[int, ...]
    failed_message_ids: tuple[int, ...]
    revoke: bool
    successful: bool


class TelegramDeleteService:
    """Delete Telegram messages."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def delete_messages(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_ids: Sequence[int],
        *,
        revoke: bool = True,
    ) -> TelegramDeleteResult:
        """
        Delete messages from a Telegram chat.

        revoke=True requests deletion for all participants where
        Telegram permits it.

        revoke=False removes messages only from the current account's
        history where supported.
        """
        self._validate_identifiers(
            account_id,
            chat_id,
        )
        self._validate_message_ids(message_ids)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        deleted_ids: list[int] = []
        failed_ids: list[int] = []

        requested_ids = list(message_ids)

        for start in range(
            0,
            len(requested_ids),
            MAX_DELETE_BATCH_SIZE,
        ):
            batch = requested_ids[
                start:start + MAX_DELETE_BATCH_SIZE
            ]

            try:
                await client.delete_messages(
                    entity,
                    batch,
                    revoke=revoke,
                )

                deleted_ids.extend(batch)

                logger.info(
                    "telegram_messages_deleted",
                    account_id=account_id,
                    chat_id=chat_id,
                    message_count=len(batch),
                    revoke=revoke,
                )

            except FloodWaitError:
                logger.warning(
                    "telegram_message_delete_flood_wait",
                    account_id=account_id,
                    chat_id=chat_id,
                    message_count=len(batch),
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
                    "telegram_message_batch_delete_failed",
                    account_id=account_id,
                    chat_id=chat_id,
                    message_count=len(batch),
                )

                # Retry individually to identify failures.
                for message_id in batch:
                    try:
                        await client.delete_messages(
                            entity,
                            [message_id],
                            revoke=revoke,
                        )
                        deleted_ids.append(message_id)

                    except FloodWaitError:
                        raise

                    except Exception:
                        failed_ids.append(message_id)

                        logger.warning(
                            "telegram_single_message_delete_failed",
                            account_id=account_id,
                            chat_id=chat_id,
                            message_id=message_id,
                            exc_info=True,
                        )

            except Exception:
                logger.exception(
                    "telegram_message_delete_unexpected_error",
                    account_id=account_id,
                    chat_id=chat_id,
                )

                raise

        successful = not failed_ids

        result = TelegramDeleteResult(
            account_id=account_id,
            chat_id=chat_id,
            requested_message_ids=tuple(requested_ids),
            deleted_message_ids=tuple(deleted_ids),
            failed_message_ids=tuple(failed_ids),
            revoke=revoke,
            successful=successful,
        )

        logger.info(
            "telegram_delete_operation_completed",
            account_id=account_id,
            chat_id=chat_id,
            requested_count=len(requested_ids),
            deleted_count=len(deleted_ids),
            failed_count=len(failed_ids),
            revoke=revoke,
            successful=successful,
        )

        return result

    async def delete_message(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
        *,
        revoke: bool = True,
    ) -> TelegramDeleteResult:
        """Delete a single Telegram message."""
        return await self.delete_messages(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            chat_id=chat_id,
            message_ids=[message_id],
            revoke=revoke,
        )

    async def delete_my_messages(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_ids: Sequence[int],
    ) -> TelegramDeleteResult:
        """
        Delete messages from the current account's history.

        This is equivalent to requesting revoke=False.
        """
        return await self.delete_messages(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            chat_id=chat_id,
            message_ids=message_ids,
            revoke=False,
        )

    async def delete_for_everyone(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_ids: Sequence[int],
    ) -> TelegramDeleteResult:
        """
        Request deletion for all participants.

        Telegram may reject this operation depending on message
        ownership, chat type, permissions, and server-side limits.
        """
        return await self.delete_messages(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            chat_id=chat_id,
            message_ids=message_ids,
            revoke=True,
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
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

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
