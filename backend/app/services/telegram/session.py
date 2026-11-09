"""
Telegram session lifecycle service.

Coordinates Telethon client connections and authorization checks
through TelegramClientManager.

This service does not directly manipulate Telethon session files.
Session storage and client construction remain the responsibility
of TelegramClientManager.
"""

from __future__ import annotations

import structlog
from telethon import TelegramClient

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


class TelegramSessionService:
    """
    Manage Telegram session connectivity and authorization.

    Args:
        client_manager: Shared Telegram client manager.
    """

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
    ) -> TelegramClient:
        """
        Connect a Telegram account and return its Telethon client.

        This establishes network connectivity but does not guarantee
        that the Telegram session is authenticated.
        """
        client = await self.client_manager.get_client(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            connect=True,
        )

        logger.info(
            "telegram_session_connected",
            account_id=account_id,
        )

        return client

    async def is_connected(self, account_id: int) -> bool:
        """
        Check whether an account's managed client is connected.

        Returns False when the account has no managed client.
        """
        client = self._get_managed_client(account_id)

        return client is not None and client.is_connected()

    async def is_authorized(self, account_id: int) -> bool:
        """
        Check whether an account has a valid Telegram authorization.

        Returns False when no managed client exists, the client is
        disconnected, or Telegram reports that it is unauthorized.
        """
        client = self._get_managed_client(account_id)

        if client is None or not client.is_connected():
            return False

        try:
            return await client.is_user_authorized()
        except Exception:
            logger.exception(
                "telegram_session_authorization_check_failed",
                account_id=account_id,
            )
            raise

    async def validate_session(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> bool:
        """
        Connect an account if necessary and verify its authorization.

        Returns:
            True if the Telegram session is authorized, otherwise False.
        """
        client = await self.connect(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
        )

        try:
            authorized = await client.is_user_authorized()
        except Exception:
            logger.exception(
                "telegram_session_validation_failed",
                account_id=account_id,
            )
            raise

        logger.info(
            "telegram_session_validation_completed",
            account_id=account_id,
            authorized=authorized,
        )

        return authorized

    async def disconnect(self, account_id: int) -> None:
        """Disconnect an account's managed Telegram client."""
        await self.client_manager.disconnect(account_id)

        logger.info(
            "telegram_session_disconnected",
            account_id=account_id,
        )

    async def disconnect_all(self) -> None:
        """Disconnect every managed Telegram client."""
        await self.client_manager.disconnect_all()

        logger.info("all_telegram_sessions_disconnected")

    def get_connected_account_ids(self) -> list[int]:
        """Return account IDs whose managed clients are currently connected."""
        return [
            account_id
            for account_id in self.client_manager.get_managed_account_ids()
            if self._get_managed_client(account_id) is not None
            and self._get_managed_client(account_id).is_connected()
        ]

    def _get_managed_client(
        self,
        account_id: int,
    ) -> TelegramClient | None:
        """
        Retrieve an already-managed client without creating a new one.

        This uses the manager's in-memory registry. It does not establish
        a connection or load a session from disk.
        """
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        return self.client_manager._clients.get(account_id)
