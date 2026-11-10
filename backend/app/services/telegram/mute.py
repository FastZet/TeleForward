"""
Telegram chat notification settings service.

Supports:
- Temporary chat muting.
- Permanent chat muting.
- Unmuting chats.
- Retrieving notification settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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

PERMANENT_MUTE_TIMESTAMP = 2**31 - 1


@dataclass(frozen=True, slots=True)
class TelegramMuteResult:
    """Normalised Telegram notification settings."""

    chat_id: int
    is_muted: bool
    mute_until: datetime | None
    is_permanent: bool
    show_previews: bool | None
    silent: bool | None


class TelegramMuteService:
    """Manage notification settings for Telegram chats."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def mute_chat(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        *,
        duration: timedelta | None = None,
        show_previews: bool | None = None,
        silent: bool | None = None,
    ) -> TelegramMuteResult:
        """
        Mute a chat.

        Args:
            duration:
                Mute duration. None means permanent mute.
            show_previews:
                Optional notification-preview preference.
            silent:
                Optional silent-notification preference.
        """
        self._validate_identifiers(account_id, chat_id)

        if duration is not None and duration.total_seconds() <= 0:
            raise ValueError(
                "Mute duration must be greater than zero."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        peer = await self._get_notify_peer(
            client,
            chat_id,
        )

        if duration is None:
            mute_until = PERMANENT_MUTE_TIMESTAMP
        else:
            mute_until = int(
                (
                    datetime.now(timezone.utc) + duration
                ).timestamp()
            )

            if mute_until >= PERMANENT_MUTE_TIMESTAMP:
                mute_until = PERMANENT_MUTE_TIMESTAMP

        settings = types.InputPeerNotifySettings(
            mute_until=mute_until,
            show_previews=show_previews,
            silent=silent,
        )

        try:
            await client(
                functions.account.UpdateNotifySettingsRequest(
                    peer=peer,
                    settings=settings,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_chat_mute_flood_wait",
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
                "telegram_chat_mute_failed",
                account_id=account_id,
                chat_id=chat_id,
            )
            raise

        logger.info(
            "telegram_chat_muted",
            account_id=account_id,
            chat_id=chat_id,
            mute_until=mute_until,
        )

        return self._build_result(
            chat_id=chat_id,
            mute_until=mute_until,
            show_previews=show_previews,
            silent=silent,
        )

    async def unmute_chat(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> TelegramMuteResult:
        """Remove the mute setting from a chat."""
        self._validate_identifiers(account_id, chat_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        peer = await self._get_notify_peer(
            client,
            chat_id,
        )

        try:
            await client(
                functions.account.UpdateNotifySettingsRequest(
                    peer=peer,
                    settings=types.InputPeerNotifySettings(
                        mute_until=0,
                    ),
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_chat_unmute_flood_wait",
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
                "telegram_chat_unmute_failed",
                account_id=account_id,
                chat_id=chat_id,
            )
            raise

        logger.info(
            "telegram_chat_unmuted",
            account_id=account_id,
            chat_id=chat_id,
        )

        return TelegramMuteResult(
            chat_id=chat_id,
            is_muted=False,
            mute_until=None,
            is_permanent=False,
            show_previews=None,
            silent=None,
        )

    async def get_mute_settings(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> TelegramMuteResult:
        """Retrieve notification settings for a chat."""
        self._validate_identifiers(account_id, chat_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        peer = await self._get_notify_peer(
            client,
            chat_id,
        )

        try:
            settings = await client(
                functions.account.GetNotifySettingsRequest(
                    peer=peer,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_chat_notification_settings_flood_wait",
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
                "telegram_chat_notification_settings_failed",
                account_id=account_id,
                chat_id=chat_id,
            )
            raise

        mute_until = getattr(settings, "mute_until", 0) or 0

        return self._build_result(
            chat_id=chat_id,
            mute_until=mute_until,
            show_previews=getattr(
                settings,
                "show_previews",
                None,
            ),
            silent=getattr(
                settings,
                "silent",
                None,
            ),
        )

    @staticmethod
    def _build_result(
        chat_id: int,
        mute_until: int,
        show_previews: bool | None,
        silent: bool | None,
    ) -> TelegramMuteResult:
        """Convert Telegram notification settings into a result."""
        now = int(datetime.now(timezone.utc).timestamp())

        is_muted = mute_until > now

        is_permanent = (
            is_muted
            and mute_until >= PERMANENT_MUTE_TIMESTAMP
        )

        mute_until_datetime = (
            datetime.fromtimestamp(
                mute_until,
                tz=timezone.utc,
            )
            if is_muted and not is_permanent
            else None
        )

        return TelegramMuteResult(
            chat_id=chat_id,
            is_muted=is_muted,
            mute_until=mute_until_datetime,
            is_permanent=is_permanent,
            show_previews=show_previews,
            silent=silent,
        )

    async def _get_authorized_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Retrieve an authorised Telegram client."""
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
    async def _get_notify_peer(
        client: TelegramClient,
        chat_id: int,
    ) -> types.InputNotifyPeer:
        """Resolve a chat into Telegram's notification-peer type."""
        entity = await client.get_input_entity(chat_id)

        return types.InputNotifyPeer(peer=entity)

    @staticmethod
    def _validate_identifiers(
        account_id: int,
        chat_id: int,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")
