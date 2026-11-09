"""
Telegram account management service.

Provides database-backed operations for Telegram accounts, including
creation, retrieval, status management, primary-account selection,
and authentication metadata updates.

Encryption and decryption of session data must be handled by the
dedicated security service before data reaches this service.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models.telegram_account import (
    TelegramAccount,
    TelegramAccountStatus,
)
from app.services.base import BaseService


logger = structlog.get_logger(__name__)


class TelegramAccountService(BaseService):
    """Manage persistent Telegram account records."""

    async def create_account(
        self,
        *,
        name: str,
        phone_number: str,
        is_primary: bool = False,
    ) -> TelegramAccount:
        """
        Create a Telegram account record.

        The account starts in PENDING status. Telegram authentication
        is performed separately by TelegramAuthenticationService.

        The caller owns the transaction and must commit or roll back.
        """
        name = name.strip()
        phone_number = phone_number.strip()

        if not name:
            raise ValueError("Account name cannot be empty.")

        if not phone_number:
            raise ValueError("Phone number cannot be empty.")

        existing = await self.session.scalar(
            select(TelegramAccount.id).where(
                TelegramAccount.phone_number == phone_number
            )
        )

        if existing is not None:
            raise ValueError(
                "A Telegram account with this phone number already exists."
            )

        if is_primary:
            await self.session.execute(
                update(TelegramAccount).values(is_primary=False)
            )

        account = TelegramAccount(
            name=name,
            phone_number=phone_number,
            status=TelegramAccountStatus.PENDING,
            is_enabled=True,
            is_primary=is_primary,
        )

        self.session.add(account)

        try:
            await self.session.flush()
        except IntegrityError:
            logger.exception(
                "telegram_account_creation_failed",
                phone_number=phone_number,
            )
            raise

        logger.info(
            "telegram_account_created",
            account_id=account.id,
            is_primary=is_primary,
        )

        return account

    async def get_account(
        self,
        account_id: int,
    ) -> TelegramAccount | None:
        """Retrieve an account by its internal database ID."""
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        return await self.session.get(TelegramAccount, account_id)

    async def get_account_or_raise(
        self,
        account_id: int,
    ) -> TelegramAccount:
        """Retrieve an account or raise LookupError."""
        account = await self.get_account(account_id)

        if account is None:
            raise LookupError(
                f"Telegram account {account_id} was not found."
            )

        return account

    async def list_accounts(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[TelegramAccount]:
        """Return all Telegram accounts, optionally filtering disabled ones."""
        statement = select(TelegramAccount).order_by(
            TelegramAccount.is_primary.desc(),
            TelegramAccount.id.asc(),
        )

        if enabled_only:
            statement = statement.where(
                TelegramAccount.is_enabled.is_(True)
            )

        result = await self.session.scalars(statement)
        return list(result.all())

    async def get_primary_account(self) -> TelegramAccount | None:
        """Return the currently designated primary account."""
        statement = (
            select(TelegramAccount)
            .where(TelegramAccount.is_primary.is_(True))
            .limit(1)
        )

        return await self.session.scalar(statement)

    async def set_primary(
        self,
        account_id: int,
    ) -> TelegramAccount:
        """
        Designate an account as primary.

        Only one account is designated primary at a time.
        """
        account = await self.get_account_or_raise(account_id)

        if not account.is_enabled:
            raise ValueError(
                "A disabled Telegram account cannot be primary."
            )

        await self.session.execute(
            update(TelegramAccount)
            .where(TelegramAccount.id != account_id)
            .values(is_primary=False)
        )

        account.is_primary = True

        await self.session.flush()

        logger.info(
            "telegram_primary_account_changed",
            account_id=account_id,
        )

        return account

    async def set_enabled(
        self,
        account_id: int,
        *,
        enabled: bool,
    ) -> TelegramAccount:
        """
        Enable or disable an account.

        Disabling an account also removes its primary designation and
        changes its status to DISABLED.

        Re-enabling an account changes its status to DISCONNECTED.
        """
        account = await self.get_account_or_raise(account_id)

        account.is_enabled = enabled

        if enabled:
            if account.status == TelegramAccountStatus.DISABLED:
                account.status = TelegramAccountStatus.DISCONNECTED
        else:
            account.is_primary = False
            account.status = TelegramAccountStatus.DISABLED

        await self.session.flush()

        logger.info(
            "telegram_account_enabled_state_changed",
            account_id=account_id,
            enabled=enabled,
        )

        return account

    async def update_status(
        self,
        account_id: int,
        status: TelegramAccountStatus,
        *,
        error: str | None = None,
    ) -> TelegramAccount:
        """
        Update an account's lifecycle status.

        Connection and authentication timestamps are updated when
        the corresponding successful states are reached.
        """
        account = await self.get_account_or_raise(account_id)

        if not isinstance(status, TelegramAccountStatus):
            raise ValueError("Invalid Telegram account status.")

        if (
            status != TelegramAccountStatus.DISABLED
            and not account.is_enabled
        ):
            raise ValueError(
                "A disabled account cannot transition to an active status."
            )

        now = datetime.now(timezone.utc)

        account.status = status

        if status == TelegramAccountStatus.CONNECTED:
            account.last_connected_at = now
            account.last_error = None

        elif status in {
            TelegramAccountStatus.REQUIRES_AUTH,
            TelegramAccountStatus.REQUIRES_2FA,
        }:
            account.last_error = error

        elif status == TelegramAccountStatus.ERROR:
            account.last_error = error or "An unspecified Telegram error occurred."

        elif status in {
            TelegramAccountStatus.PENDING,
            TelegramAccountStatus.DISCONNECTED,
            TelegramAccountStatus.DISABLED,
        }:
            account.last_error = None

        await self.session.flush()

        logger.info(
            "telegram_account_status_updated",
            account_id=account_id,
            status=status.value,
        )

        return account

    async def update_identity(
        self,
        account_id: int,
        *,
        telegram_user_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> TelegramAccount:
        """
        Store the Telegram identity obtained after successful authentication.

        This method does not store API credentials or authentication
        passwords.
        """
        if telegram_user_id <= 0:
            raise ValueError("telegram_user_id must be positive.")

        account = await self.get_account_or_raise(account_id)

        account.telegram_user_id = telegram_user_id
        account.telegram_username = username
        account.first_name = first_name
        account.last_name = last_name
        account.last_authenticated_at = datetime.now(timezone.utc)
        account.last_error = None

        await self.session.flush()

        logger.info(
            "telegram_account_identity_updated",
            account_id=account_id,
            telegram_user_id=telegram_user_id,
        )

        return account

    async def store_encrypted_session(
        self,
        account_id: int,
        encrypted_session: str,
    ) -> TelegramAccount:
        """
        Store an already-encrypted Telegram session payload.

        Encryption must be performed by the dedicated security service.
        Plaintext session material must never be passed to this method.
        """
        if not encrypted_session or not encrypted_session.strip():
            raise ValueError("Encrypted session data cannot be empty.")

        account = await self.get_account_or_raise(account_id)

        account.session_data_encrypted = encrypted_session

        await self.session.flush()

        logger.info(
            "telegram_account_session_updated",
            account_id=account_id,
        )

        return account

    async def clear_encrypted_session(
        self,
        account_id: int,
    ) -> TelegramAccount:
        """Remove the stored encrypted session payload."""
        account = await self.get_account_or_raise(account_id)

        account.session_data_encrypted = None

        await self.session.flush()

        logger.info(
            "telegram_account_session_cleared",
            account_id=account_id,
        )

        return account

    async def rename_account(
        self,
        account_id: int,
        name: str,
    ) -> TelegramAccount:
        """Change an account's display name."""
        name = name.strip()

        if not name:
            raise ValueError("Account name cannot be empty.")

        account = await self.get_account_or_raise(account_id)
        account.name = name

        await self.session.flush()

        return account
