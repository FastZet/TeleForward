"""
Telegram message-editing service.

Supports editing message text and media captions while preserving
formatting entities when requested.
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
    MessageNotModifiedError,
    PeerIdInvalidError,
)
from telethon.tl.custom.message import Message

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramEditResult:
    """Result of editing a Telegram message."""

    account_id: int
    chat_id: int
    message_id: int
    successful: bool
    changed: bool
    message_text: str | None = None


class TelegramEditService:
    """Edit Telegram message text and media captions."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def edit_message(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
        new_text: str,
        *,
        formatting_entities: Sequence[object] | None = None,
        preserve_formatting: bool = True,
        link_preview: bool = True,
    ) -> TelegramEditResult:
        """
        Edit a Telegram message or media caption.

        If preserve_formatting is enabled and no replacement entities
        are supplied, existing formatting entities are retained.
        """
        self._validate_identifiers(
            account_id,
            chat_id,
            message_id,
        )

        if not isinstance(new_text, str):
            raise TypeError("new_text must be a string.")

        if len(new_text) > 4096:
            raise ValueError(
                "Telegram message text cannot exceed 4096 characters."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        original = await client.get_messages(
            entity,
            ids=message_id,
        )

        if not isinstance(original, Message):
            raise ValueError(
                f"Telegram message {message_id} could not be found."
            )

        if original.action is not None:
            raise ValueError(
                "Telegram service messages cannot be edited."
            )

        if original.out is False:
            raise PermissionError(
                "The authenticated account cannot edit this incoming message."
            )

        if formatting_entities is not None:
            entities = list(formatting_entities)
        elif preserve_formatting:
            entities = original.entities
        else:
            entities = None

        try:
            edited = await client.edit_message(
                entity,
                message_id,
                text=new_text,
                formatting_entities=entities,
                link_preview=link_preview,
                parse_mode=None,
            )

        except MessageNotModifiedError:
            logger.debug(
                "telegram_message_unchanged",
                account_id=account_id,
                chat_id=chat_id,
                message_id=message_id,
            )

            return TelegramEditResult(
                account_id=account_id,
                chat_id=chat_id,
                message_id=message_id,
                successful=True,
                changed=False,
                message_text=original.message,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_message_edit_flood_wait",
                account_id=account_id,
                chat_id=chat_id,
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
                "telegram_message_edit_failed",
                account_id=account_id,
                chat_id=chat_id,
                message_id=message_id,
            )
            raise

        if not isinstance(edited, Message):
            raise RuntimeError(
                "Telegram did not return an edited message."
            )

        logger.info(
            "telegram_message_edited",
            account_id=account_id,
            chat_id=chat_id,
            message_id=message_id,
        )

        return TelegramEditResult(
            account_id=account_id,
            chat_id=chat_id,
            message_id=message_id,
            successful=True,
            changed=True,
            message_text=edited.message,
        )

    async def edit_caption(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
        new_caption: str,
        *,
        formatting_entities: Sequence[object] | None = None,
        preserve_formatting: bool = True,
    ) -> TelegramEditResult:
        """Edit the caption of a Telegram media message."""
        self._validate_identifiers(
            account_id,
            chat_id,
            message_id,
        )

        if not isinstance(new_caption, str):
            raise TypeError("new_caption must be a string.")

        if len(new_caption) > 4096:
            raise ValueError(
                "Telegram caption cannot exceed 4096 characters."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        original = await client.get_messages(
            entity,
            ids=message_id,
        )

        if not isinstance(original, Message):
            raise ValueError(
                f"Telegram message {message_id} could not be found."
            )

        if original.media is None:
            raise ValueError(
                "The specified message does not contain media."
            )

        if original.action is not None:
            raise ValueError(
                "Telegram service messages cannot be edited."
            )

        if original.out is False:
            raise PermissionError(
                "The authenticated account cannot edit this incoming message."
            )

        if formatting_entities is not None:
            entities = list(formatting_entities)
        elif preserve_formatting:
            entities = original.entities
        else:
            entities = None

        try:
            edited = await client.edit_message(
                entity,
                message_id,
                text=new_caption,
                formatting_entities=entities,
                parse_mode=None,
            )

        except MessageNotModifiedError:
            return TelegramEditResult(
                account_id=account_id,
                chat_id=chat_id,
                message_id=message_id,
                successful=True,
                changed=False,
                message_text=original.message,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_caption_edit_flood_wait",
                account_id=account_id,
                chat_id=chat_id,
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
                "telegram_caption_edit_failed",
                account_id=account_id,
                chat_id=chat_id,
                message_id=message_id,
            )
            raise

        if not isinstance(edited, Message):
            raise RuntimeError(
                "Telegram did not return an edited message."
            )

        logger.info(
            "telegram_caption_edited",
            account_id=account_id,
            chat_id=chat_id,
            message_id=message_id,
        )

        return TelegramEditResult(
            account_id=account_id,
            chat_id=chat_id,
            message_id=message_id,
            successful=True,
            changed=True,
            message_text=edited.message,
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
        message_id: int,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

        if message_id <= 0:
            raise ValueError("message_id must be positive.")
