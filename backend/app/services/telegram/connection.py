"""
Telegram connection management service.

Supports:
- Connecting Telegram accounts.
- Disconnecting Telegram accounts.
- Checking connection status.
- Checking authorisation status.
- Testing Telegram API connectivity.
- Reconnecting disconnected accounts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramConnectionStatus:
    """Telegram account connection status."""

    account_id: int
    connected: bool
    authorised: bool
    responsive: bool
    user_id: int | None
    username: str | None
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class TelegramConnectionResult:
    """Result of a connection operation."""

    account_id: int
    successful: bool
    connected: bool
    authorised: bool
    error: str | None = None


class TelegramConnectionService:
    """Manage Telegram client connections."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def connect(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramConnectionResult:
        """Connect a Telegram account."""
        client = await self._get_client(
            account_id,
            api_id,
            api_hash,
            connect=False,
        )

        try:
            if not client.is_connected():
                await client.connect()

            authorised = await client.is_user_authorized()

            logger.info(
                "telegram_account_connected",
                account_id=account_id,
                authorised=authorised,
            )

            return TelegramConnectionResult(
                account_id=account_id,
                successful=True,
                connected=client.is_connected(),
                authorised=authorised,
            )

        except Exception as exc:
            logger.exception(
                "telegram_account_connection_failed",
                account_id=account_id,
            )

            return TelegramConnectionResult(
                account_id=account_id,
                successful=False,
                connected=client.is_connected(),
                authorised=False,
                error=type(exc).__name__,
            )

    async def disconnect(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramConnectionResult:
        """Disconnect a Telegram account without deleting its session."""
        client = await self._get_client(
            account_id,
            api_id,
            api_hash,
            connect=False,
        )

        try:
            if client.is_connected():
                await client.disconnect()

            logger.info(
                "telegram_account_disconnected",
                account_id=account_id,
            )

            return TelegramConnectionResult(
                account_id=account_id,
                successful=True,
                connected=False,
                authorised=False,
            )

        except Exception as exc:
            logger.exception(
                "telegram_account_disconnection_failed",
                account_id=account_id,
            )

            return TelegramConnectionResult(
                account_id=account_id,
                successful=False,
                connected=client.is_connected(),
                authorised=False,
                error=type(exc).__name__,
            )

    async def get_status(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramConnectionStatus:
        """Retrieve the current Telegram connection status."""
        client = await self._get_client(
            account_id,
            api_id,
            api_hash,
            connect=False,
        )

        connected = client.is_connected()
        authorised = False
        responsive = False
        user_id = None
        username = None

        if connected:
            try:
                authorised = await client.is_user_authorized()

                if authorised:
                    me = await client.get_me()

                    if me is not None:
                        responsive = True
                        user_id = me.id
                        username = getattr(
                            me,
                            "username",
                            None,
                        )

            except FloodWaitError:
                logger.warning(
                    "telegram_connection_status_flood_wait",
                    account_id=account_id,
                )
                raise

            except Exception:
                logger.exception(
                    "telegram_connection_status_check_failed",
                    account_id=account_id,
                )

        return TelegramConnectionStatus(
            account_id=account_id,
            connected=connected,
            authorised=authorised,
            responsive=responsive,
            user_id=user_id,
            username=username,
            checked_at=datetime.now(timezone.utc),
        )

    async def test_connection(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> bool:
        """Test whether the Telegram account can communicate with Telegram."""
        client = await self._get_client(
            account_id,
            api_id,
            api_hash,
            connect=True,
        )

        if not client.is_connected():
            return False

        try:
            if not await client.is_user_authorized():
                return False

            me = await client.get_me()

            return me is not None

        except FloodWaitError:
            logger.warning(
                "telegram_connection_test_flood_wait",
                account_id=account_id,
            )
            raise

        except Exception:
            logger.exception(
                "telegram_connection_test_failed",
                account_id=account_id,
            )
            return False

    async def reconnect(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramConnectionResult:
        """Reconnect a disconnected Telegram account."""
        client = await self._get_client(
            account_id,
            api_id,
            api_hash,
            connect=False,
        )

        try:
            if client.is_connected():
                await client.disconnect()

            await client.connect()

            authorised = await client.is_user_authorized()

            logger.info(
                "telegram_account_reconnected",
                account_id=account_id,
                authorised=authorised,
            )

            return TelegramConnectionResult(
                account_id=account_id,
                successful=True,
                connected=client.is_connected(),
                authorised=authorised,
            )

        except Exception as exc:
            logger.exception(
                "telegram_account_reconnection_failed",
                account_id=account_id,
            )

            return TelegramConnectionResult(
                account_id=account_id,
                successful=False,
                connected=client.is_connected(),
                authorised=False,
                error=type(exc).__name__,
            )

    async def _get_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        connect: bool,
    ) -> TelegramClient:
        """Retrieve a managed Telegram client."""
        if account_id <= 0:
            raise ValueError(
                "account_id must be positive."
            )

        if api_id <= 0:
            raise ValueError(
                "api_id must be positive."
            )

        if not api_hash.strip():
            raise ValueError(
                "api_hash cannot be empty."
            )

        return await self.client_manager.get_client(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            connect=connect,
        )
