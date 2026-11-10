"""
Telegram username service.

Supports:
- Resolving usernames to Telegram entities.
- Retrieving username information.
- Checking username availability.
- Updating the authenticated account's username.
- Removing the authenticated account's username.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from telethon import TelegramClient, functions, types
from telethon.errors import (
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotModifiedError,
    UsernameOccupiedError,
)

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

USERNAME_PATTERN = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9_]{4,31}$"
)


@dataclass(frozen=True, slots=True)
class TelegramUsernameResult:
    """Normalised username information."""

    user_id: int
    username: str | None
    display_name: str | None
    is_bot: bool
    is_verified: bool
    is_premium: bool


@dataclass(frozen=True, slots=True)
class TelegramUsernameUpdateResult:
    """Result of a username update operation."""

    account_id: int
    username: str | None
    successful: bool


class TelegramUsernameService:
    """Manage Telegram username operations."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def resolve_username(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        username: str,
    ) -> TelegramUsernameResult:
        """Resolve a public Telegram username."""
        normalised_username = self._normalise_username(username)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            entity = await client.get_entity(
                normalised_username
            )

        except FloodWaitError:
            logger.warning(
                "telegram_username_resolution_flood_wait",
                account_id=account_id,
            )
            raise

        if not isinstance(entity, types.User):
            raise ValueError(
                "The supplied username does not belong to a Telegram user."
            )

        display_name = " ".join(
            part
            for part in (
                entity.first_name,
                entity.last_name,
            )
            if part
        ) or None

        return TelegramUsernameResult(
            user_id=entity.id,
            username=entity.username,
            display_name=display_name,
            is_bot=bool(entity.bot),
            is_verified=bool(entity.verified),
            is_premium=bool(
                getattr(entity, "premium", False)
            ),
        )

    async def check_username_availability(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        username: str,
    ) -> bool:
        """
        Check whether a username is available for the current account.

        Telegram performs the authoritative availability check.
        """
        normalised_username = self._normalise_username(username)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            return bool(
                await client(
                    functions.account.CheckUsernameRequest(
                        username=normalised_username,
                    )
                )
            )

        except UsernameOccupiedError:
            return False

        except UsernameInvalidError:
            raise ValueError(
                "Telegram rejected the supplied username as invalid."
            )

        except FloodWaitError:
            logger.warning(
                "telegram_username_availability_flood_wait",
                account_id=account_id,
            )
            raise

    async def update_username(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        username: str,
    ) -> TelegramUsernameUpdateResult:
        """Set or change the authenticated account's username."""
        normalised_username = self._normalise_username(username)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            await client(
                functions.account.UpdateUsernameRequest(
                    username=normalised_username,
                )
            )

        except UsernameOccupiedError:
            logger.warning(
                "telegram_username_already_occupied",
                account_id=account_id,
            )
            raise

        except UsernameInvalidError:
            raise ValueError(
                "Telegram rejected the supplied username as invalid."
            )

        except UsernameNotModifiedError:
            return TelegramUsernameUpdateResult(
                account_id=account_id,
                username=normalised_username,
                successful=True,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_username_update_flood_wait",
                account_id=account_id,
            )
            raise

        logger.info(
            "telegram_username_updated",
            account_id=account_id,
        )

        return TelegramUsernameUpdateResult(
            account_id=account_id,
            username=normalised_username,
            successful=True,
        )

    async def remove_username(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramUsernameUpdateResult:
        """Remove the authenticated account's public username."""
        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            await client(
                functions.account.UpdateUsernameRequest(
                    username="",
                )
            )

        except UsernameNotModifiedError:
            return TelegramUsernameUpdateResult(
                account_id=account_id,
                username=None,
                successful=True,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_username_removal_flood_wait",
                account_id=account_id,
            )
            raise

        logger.info(
            "telegram_username_removed",
            account_id=account_id,
        )

        return TelegramUsernameUpdateResult(
            account_id=account_id,
            username=None,
            successful=True,
        )

    @staticmethod
    def _normalise_username(username: str) -> str:
        """Validate and normalise a Telegram username."""
        if not isinstance(username, str):
            raise ValueError(
                "Username must be a string."
            )

        normalised = username.strip().lstrip("@")

        if not USERNAME_PATTERN.fullmatch(normalised):
            raise ValueError(
                "Username must contain 5–32 characters, "
                "start with a letter, and contain only letters, "
                "numbers or underscores."
            )

        return normalised

    async def _get_authorized_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Retrieve an authorised Telegram client."""
        if account_id <= 0:
            raise ValueError(
                "account_id must be positive."
            )

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
