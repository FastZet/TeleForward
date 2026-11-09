"""
Telegram authentication service.

Handles phone-number authentication, verification codes, and Telegram
two-factor authentication using managed Telethon clients.

Pending authentication challenges are maintained server-side and are
associated with individual TeleForward account IDs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from telethon import TelegramClient
from telethon.errors import (
    AuthRestartError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AuthChallenge:
    """Result returned after requesting a Telegram verification code."""

    account_id: int
    phone_number: str
    code_type: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthResult:
    """Result returned after successful Telegram authentication."""

    account_id: int
    telegram_user_id: int
    username: str | None
    phone_number: str | None
    requires_password: bool = False


@dataclass(slots=True)
class _PendingAuthentication:
    """Server-side state for an incomplete Telegram authentication."""

    phone_number: str
    phone_code_hash: str
    expires_at: datetime
    requires_password: bool = False


class TelegramAuthenticationService:
    """
    Manage Telegram authentication workflows.

    The service does not persist account records or API credentials.
    Those responsibilities belong to the account and credential services.

    Args:
        client_manager: Shared Telegram client manager.
        challenge_ttl_seconds: Maximum lifetime of a pending authentication
            challenge.
    """

    def __init__(
        self,
        client_manager: TelegramClientManager,
        *,
        challenge_ttl_seconds: int = 600,
    ) -> None:
        if challenge_ttl_seconds <= 0:
            raise ValueError("challenge_ttl_seconds must be positive.")

        self.client_manager = client_manager
        self.challenge_ttl_seconds = challenge_ttl_seconds

        self._pending: dict[int, _PendingAuthentication] = {}
        self._lock = asyncio.Lock()

    async def _get_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Retrieve an account's managed client without connecting it."""
        return await self.client_manager.get_client(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
            connect=True,
        )

    async def request_code(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        phone_number: str,
    ) -> AuthChallenge:
        """
        Request a Telegram login verification code.

        A new request replaces any existing pending challenge for the
        account.

        Raises:
            ValueError: If the account or phone number is invalid.
            PhoneNumberInvalidError: If Telegram rejects the phone number.
        """
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        phone_number = phone_number.strip()

        if not phone_number:
            raise ValueError("phone_number cannot be empty.")

        client = await self._get_client(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
        )

        async with self._lock:
            sent_code = await client.send_code_request(phone_number)

            expires_at = datetime.now(timezone.utc).timestamp()
            expires_at += self.challenge_ttl_seconds

            self._pending[account_id] = _PendingAuthentication(
                phone_number=phone_number,
                phone_code_hash=sent_code.phone_code_hash,
                expires_at=datetime.fromtimestamp(
                    expires_at,
                    tz=timezone.utc,
                ),
            )

        logger.info(
            "telegram_auth_code_requested",
            account_id=account_id,
            code_type=type(sent_code).__name__,
        )

        return AuthChallenge(
            account_id=account_id,
            phone_number=phone_number,
            code_type=type(sent_code).__name__,
            expires_at=datetime.fromtimestamp(
                expires_at,
                tz=timezone.utc,
            ),
        )

    async def submit_code(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        phone_code: str,
    ) -> AuthResult:
        """
        Submit a Telegram verification code.

        If the account has Telegram 2FA enabled, the service retains the
        pending challenge and raises SessionPasswordNeededError.

        The caller must then invoke submit_password().
        """
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        phone_code = phone_code.strip()

        if not phone_code:
            raise ValueError("phone_code cannot be empty.")

        client = await self._get_client(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
        )

        async with self._lock:
            pending = self._get_pending(account_id)

            try:
                user = await client.sign_in(
                    phone=pending.phone_number,
                    code=phone_code,
                    phone_code_hash=pending.phone_code_hash,
                )

            except SessionPasswordNeededError:
                pending.requires_password = True

                logger.info(
                    "telegram_auth_requires_password",
                    account_id=account_id,
                )
                raise

            except (
                PhoneCodeInvalidError,
                PhoneCodeExpiredError,
                AuthRestartError,
            ):
                self._pending.pop(account_id, None)
                raise

            self._pending.pop(account_id, None)

        return self._build_auth_result(account_id, user)

    async def submit_password(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        password: str,
    ) -> AuthResult:
        """
        Complete Telegram authentication using the account's 2FA password.

        The password is passed directly to Telethon and is never stored
        in the service's pending authentication state.
        """
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if not password:
            raise ValueError("password cannot be empty.")

        client = await self._get_client(
            account_id=account_id,
            api_id=api_id,
            api_hash=api_hash,
        )

        async with self._lock:
            pending = self._get_pending(account_id)

            if not pending.requires_password:
                raise ValueError(
                    "Two-factor authentication has not been requested."
                )

            try:
                user = await client.sign_in(password=password)

            except AuthRestartError:
                self._pending.pop(account_id, None)
                raise

            self._pending.pop(account_id, None)

        return self._build_auth_result(account_id, user)

    async def cancel_authentication(self, account_id: int) -> None:
        """Discard an account's pending authentication challenge."""
        async with self._lock:
            self._pending.pop(account_id, None)

        logger.info(
            "telegram_authentication_cancelled",
            account_id=account_id,
        )

    async def logout(self, account_id: int) -> None:
        """
        Log out a Telegram account and disconnect its managed client.

        Telethon's sign_out invalidates the stored Telegram authorization.
        """
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        async with self._lock:
            self._pending.pop(account_id, None)

            client = await self.client_manager.get_client(
                account_id=account_id,
                api_id=1,
                api_hash="logout-placeholder",
                connect=False,
            )

            if client.is_connected():
                try:
                    await client.log_out()
                finally:
                    await self.client_manager.disconnect(account_id)

        logger.info(
            "telegram_account_logged_out",
            account_id=account_id,
        )

    def _get_pending(self, account_id: int) -> _PendingAuthentication:
        """Retrieve and validate a pending authentication challenge."""
        pending = self._pending.get(account_id)

        if pending is None:
            raise ValueError(
                "No pending Telegram authentication challenge exists."
            )

        if datetime.now(timezone.utc) >= pending.expires_at:
            self._pending.pop(account_id, None)
            raise ValueError(
                "The Telegram authentication challenge has expired."
            )

        return pending

    @staticmethod
    def _build_auth_result(account_id: int, user: object) -> AuthResult:
        """Convert a Telethon user object into a transport-independent result."""
        return AuthResult(
            account_id=account_id,
            telegram_user_id=int(user.id),
            username=getattr(user, "username", None),
            phone_number=getattr(user, "phone", None),
        )
