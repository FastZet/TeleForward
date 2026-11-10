"""
Telegram chat-action service.

Supports:
- Typing indicators.
- Recording audio and video indicators.
- Uploading photos, videos, documents, and audio.
- Cancelling active chat actions.
- Configurable action duration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

import structlog
from telethon import TelegramClient, functions, types
from telethon.errors import (
    ChannelPrivateError,
    ChatIdInvalidError,
    FloodWaitError,
    PeerIdInvalidError,
)

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

DEFAULT_ACTION_DURATION = 5.0
MAX_ACTION_DURATION = 60.0


class TelegramChatAction(StrEnum):
    """Supported Telegram chat-action types."""

    TYPING = "typing"
    RECORD_AUDIO = "record_audio"
    RECORD_VIDEO = "record_video"
    RECORD_ROUND = "record_round"
    UPLOAD_PHOTO = "upload_photo"
    UPLOAD_VIDEO = "upload_video"
    UPLOAD_ROUND = "upload_round"
    UPLOAD_AUDIO = "upload_audio"
    UPLOAD_DOCUMENT = "upload_document"
    CHOOSE_STICKER = "choose_sticker"
    FIND_LOCATION = "find_location"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class TelegramChatActionResult:
    """Result of a chat-action operation."""

    account_id: int
    chat_id: int
    action: TelegramChatAction
    successful: bool


class TelegramTypingService:
    """Manage Telegram chat-action indicators."""

    ACTION_MAPPING: dict[
        TelegramChatAction,
        type[types.TypeSendMessageAction],
    ] = {
        TelegramChatAction.TYPING: types.SendMessageTypingAction,
        TelegramChatAction.RECORD_AUDIO: types.SendMessageRecordAudioAction,
        TelegramChatAction.RECORD_VIDEO: types.SendMessageRecordVideoAction,
        TelegramChatAction.RECORD_ROUND: types.SendMessageRecordRoundAction,
        TelegramChatAction.UPLOAD_PHOTO: types.SendMessageUploadPhotoAction,
        TelegramChatAction.UPLOAD_VIDEO: types.SendMessageUploadVideoAction,
        TelegramChatAction.UPLOAD_ROUND: types.SendMessageUploadRoundAction,
        TelegramChatAction.UPLOAD_AUDIO: types.SendMessageUploadAudioAction,
        TelegramChatAction.UPLOAD_DOCUMENT: types.SendMessageUploadDocumentAction,
        TelegramChatAction.CHOOSE_STICKER: types.SendMessageChooseStickerAction,
        TelegramChatAction.FIND_LOCATION: types.SendMessageGeoLocationAction,
        TelegramChatAction.CANCEL: types.SendMessageCancelAction,
    }

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def send_action(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        action: TelegramChatAction,
    ) -> TelegramChatActionResult:
        """Send a single chat-action indicator."""
        self._validate_identifiers(account_id, chat_id)

        if not isinstance(action, TelegramChatAction):
            raise ValueError("Unsupported Telegram chat action.")

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        peer = await client.get_input_entity(chat_id)

        try:
            await client(
                functions.messages.SetTypingRequest(
                    peer=peer,
                    action=self.ACTION_MAPPING[action](),
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_chat_action_flood_wait",
                account_id=account_id,
                chat_id=chat_id,
                action=action.value,
            )
            raise

        except (
            ChannelPrivateError,
            ChatIdInvalidError,
            PeerIdInvalidError,
        ):
            logger.exception(
                "telegram_chat_action_failed",
                account_id=account_id,
                chat_id=chat_id,
                action=action.value,
            )
            raise

        logger.debug(
            "telegram_chat_action_sent",
            account_id=account_id,
            chat_id=chat_id,
            action=action.value,
        )

        return TelegramChatActionResult(
            account_id=account_id,
            chat_id=chat_id,
            action=action,
            successful=True,
        )

    async def send_action_for_duration(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        action: TelegramChatAction,
        *,
        duration: float = DEFAULT_ACTION_DURATION,
        interval: float = 4.0,
    ) -> TelegramChatActionResult:
        """
        Maintain a chat-action indicator for a limited duration.

        Telegram action indicators expire automatically. This method
        periodically refreshes the indicator until the duration ends.
        """
        if not 0 < duration <= MAX_ACTION_DURATION:
            raise ValueError(
                f"duration must be greater than 0 and no more than "
                f"{MAX_ACTION_DURATION} seconds."
            )

        if not 0 < interval < duration:
            raise ValueError(
                "interval must be positive and shorter than duration."
            )

        if action == TelegramChatAction.CANCEL:
            raise ValueError(
                "CANCEL cannot be maintained for a duration."
            )

        self._validate_identifiers(account_id, chat_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        peer = await client.get_input_entity(chat_id)
        action_object = self._get_action_object(action)

        elapsed = 0.0

        while elapsed < duration:
            try:
                await client(
                    functions.messages.SetTypingRequest(
                        peer=peer,
                        action=action_object,
                    )
                )

            except FloodWaitError:
                logger.warning(
                    "telegram_chat_action_duration_flood_wait",
                    account_id=account_id,
                    chat_id=chat_id,
                    action=action.value,
                )
                raise

            remaining = duration - elapsed
            sleep_time = min(interval, remaining)

            await asyncio.sleep(sleep_time)
            elapsed += sleep_time

        await client(
            functions.messages.SetTypingRequest(
                peer=peer,
                action=types.SendMessageCancelAction(),
            )
        )

        logger.debug(
            "telegram_chat_action_duration_completed",
            account_id=account_id,
            chat_id=chat_id,
            action=action.value,
            duration=duration,
        )

        return TelegramChatActionResult(
            account_id=account_id,
            chat_id=chat_id,
            action=action,
            successful=True,
        )

    async def cancel_action(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> TelegramChatActionResult:
        """Cancel an active chat-action indicator."""
        return await self.send_action(
            account_id,
            api_id,
            api_hash,
            chat_id,
            TelegramChatAction.CANCEL,
        )

    def _get_action_object(
        self,
        action: TelegramChatAction,
    ) -> types.TypeSendMessageAction:
        if not isinstance(action, TelegramChatAction):
            raise ValueError("Unsupported Telegram chat action.")

        if action == TelegramChatAction.CANCEL:
            raise ValueError(
                "Use cancel_action() to cancel an active action."
            )

        return self.ACTION_MAPPING[action]()

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
