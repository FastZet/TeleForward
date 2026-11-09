"""
Telethon client management.

Provides a centralised lifecycle manager for Telegram clients. Each
Telegram account receives an independent persistent session file.

API credentials are supplied by the caller and must never be logged.
Session files contain authentication material and must be protected.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from telethon import TelegramClient


logger = structlog.get_logger(__name__)


class TelegramClientManager:
    """
    Manage persistent Telethon clients for multiple Telegram accounts.

    Args:
        session_dir: Directory in which Telethon session files are stored.
        connection_retries: Number of connection attempts.
        request_retries: Number of request retries.
        retry_delay: Delay between connection retries, in seconds.
        flood_sleep_threshold: Maximum flood-wait duration Telethon
            handles automatically, in seconds.
    """

    def __init__(
        self,
        session_dir: Path,
        *,
        connection_retries: int = 5,
        request_retries: int = 5,
        retry_delay: int = 2,
        flood_sleep_threshold: int = 60,
    ) -> None:
        if connection_retries < 0:
            raise ValueError("connection_retries cannot be negative.")

        if request_retries < 0:
            raise ValueError("request_retries cannot be negative.")

        if retry_delay < 0:
            raise ValueError("retry_delay cannot be negative.")

        if flood_sleep_threshold < 0:
            raise ValueError("flood_sleep_threshold cannot be negative.")

        self.session_dir = Path(session_dir).expanduser().resolve()
        self.connection_retries = connection_retries
        self.request_retries = request_retries
        self.retry_delay = retry_delay
        self.flood_sleep_threshold = flood_sleep_threshold

        self._clients: dict[int, TelegramClient] = {}
        self._lock = asyncio.Lock()

    def _prepare_session_directory(self) -> None:
        """Create the session directory with restrictive permissions."""
        self.session_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        self.session_dir.chmod(0o700)

    def _create_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Construct a Telethon client without connecting it."""
        session_path = self.session_dir / f"account_{account_id}"

        client = TelegramClient(
            str(session_path),
            api_id=api_id,
            api_hash=api_hash,
            connection_retries=self.connection_retries,
            request_retries=self.request_retries,
            retry_delay=self.retry_delay,
            auto_reconnect=True,
            flood_sleep_threshold=self.flood_sleep_threshold,
        )

        return client

    async def get_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        connect: bool = True,
    ) -> TelegramClient:
        """
        Retrieve an existing client or create a new one.

        The account ID determines the persistent session filename.
        Existing clients are reused.

        Args:
            account_id: Internal TeleForward account ID.
            api_id: Telegram application API ID.
            api_hash: Telegram application API hash.
            connect: Whether to establish the connection before returning.

        Returns:
            The account's Telethon client.

        Raises:
            ValueError: If supplied account credentials are invalid.
            Exception: Propagates connection failures after cleanup.
        """
        if account_id <= 0:
            raise ValueError("account_id must be a positive integer.")

        if api_id <= 0:
            raise ValueError("api_id must be a positive integer.")

        if not api_hash or not api_hash.strip():
            raise ValueError("api_hash cannot be empty.")

        async with self._lock:
            client = self._clients.get(account_id)

            if client is None:
                self._prepare_session_directory()

                client = self._create_client(
                    account_id=account_id,
                    api_id=api_id,
                    api_hash=api_hash,
                )

                self._clients[account_id] = client

                logger.info(
                    "telegram_client_created",
                    account_id=account_id,
                )

            if connect and not client.is_connected():
                try:
                    await client.connect()
                except Exception:
                    self._clients.pop(account_id, None)

                    try:
                        await client.disconnect()
                    except Exception:
                        logger.warning(
                            "telegram_client_cleanup_failed",
                            account_id=account_id,
                            exc_info=True,
                        )

                    logger.exception(
                        "telegram_client_connection_failed",
                        account_id=account_id,
                    )
                    raise

                logger.info(
                    "telegram_client_connected",
                    account_id=account_id,
                )

            return client

    async def disconnect(self, account_id: int) -> None:
        """Disconnect and remove a client's in-memory instance."""
        async with self._lock:
            client = self._clients.pop(account_id, None)

            if client is None:
                return

            try:
                await client.disconnect()
            except Exception:
                logger.exception(
                    "telegram_client_disconnect_failed",
                    account_id=account_id,
                )
                raise

            logger.info(
                "telegram_client_disconnected",
                account_id=account_id,
            )

    async def disconnect_all(self) -> None:
        """Disconnect all managed clients during application shutdown."""
        async with self._lock:
            clients = list(self._clients.items())
            self._clients.clear()

            results = await asyncio.gather(
                *(client.disconnect() for _, client in clients),
                return_exceptions=True,
            )

            for (account_id, _), result in zip(clients, results):
                if isinstance(result, BaseException):
                    logger.error(
                        "telegram_client_shutdown_failed",
                        account_id=account_id,
                        error_type=type(result).__name__,
                    )
                else:
                    logger.info(
                        "telegram_client_disconnected",
                        account_id=account_id,
                    )

    def get_managed_account_ids(self) -> list[int]:
        """Return the IDs of accounts currently managed in memory."""
        return list(self._clients.keys())
