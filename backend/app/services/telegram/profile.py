"""
Telegram account profile service.

Supports:
- Retrieving the authenticated account profile.
- Retrieving extended profile information.
- Updating first and last names.
- Updating the account biography.
- Updating the Telegram username.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from telethon import TelegramClient, functions, types, utils
from telethon.errors import FloodWaitError, UsernameInvalidError

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

MAX_NAME_LENGTH = 64
MAX_BIO_LENGTH = 140
MIN_USERNAME_LENGTH = 5
MAX_USERNAME_LENGTH = 32


@dataclass(frozen=True, slots=True)
class TelegramProfile:
    """Normalised Telegram account profile."""

    account_id: int
    user_id: int
    first_name: str
    last_name: str | None
    username: str | None
    phone: str | None
    about: str | None
    verified: bool
    premium: bool
    bot: bool
    scam: bool
    fake: bool
    restricted: bool


class TelegramProfileService:
    """Retrieve and update Telegram account profiles."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def get_profile(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramProfile:
        """Retrieve the authenticated account's extended profile."""
        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        me = await client.get_me()

        if not isinstance(me, types.User):
            raise RuntimeError(
                "Telegram did not return a valid user profile."
            )

        input_user = utils.get_input_user(me)

        try:
            full_user = await client(
                functions.users.GetFullUserRequest(
                    id=input_user,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_profile_retrieval_flood_wait",
                account_id=account_id,
            )
            raise

        profile_user = getattr(
            full_user,
            "users",
            None,
        )

        if profile_user:
            matching_user = next(
                (
                    user
                    for user in profile_user
                    if isinstance(user, types.User)
                    and user.id == me.id
                ),
                None,
            )
        else:
            matching_user = me

        if matching_user is None:
            matching_user = me

        profile_data = getattr(
            full_user,
            "full_user",
            None,
        )

        about = (
            getattr(profile_data, "about", None)
            if profile_data is not None
            else None
        )

        return self._normalise_profile(
            account_id=account_id,
            user=matching_user,
            about=about,
        )

    async def update_profile(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        about: str | None = None,
    ) -> TelegramProfile:
        """Update the authenticated account's display name and biography."""
        self._validate_account_id(account_id)

        if (
            first_name is None
            and last_name is None
            and about is None
        ):
            raise ValueError(
                "At least one profile field must be provided."
            )

        if first_name is not None:
            first_name = first_name.strip()

            if not first_name:
                raise ValueError(
                    "First name cannot be empty."
                )

            if len(first_name) > MAX_NAME_LENGTH:
                raise ValueError(
                    f"First name cannot exceed {MAX_NAME_LENGTH} characters."
                )

        if last_name is not None:
            last_name = last_name.strip()

            if len(last_name) > MAX_NAME_LENGTH:
                raise ValueError(
                    f"Last name cannot exceed {MAX_NAME_LENGTH} characters."
                )

        if about is not None:
            about = about.strip()

            if len(about) > MAX_BIO_LENGTH:
                raise ValueError(
                    f"Biography cannot exceed {MAX_BIO_LENGTH} characters."
                )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            await client(
                functions.account.UpdateProfileRequest(
                    first_name=first_name,
                    last_name=last_name,
                    about=about,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_profile_update_flood_wait",
                account_id=account_id,
            )
            raise

        logger.info(
            "telegram_profile_updated",
            account_id=account_id,
        )

        return await self.get_profile(
            account_id,
            api_id,
            api_hash,
        )

    async def update_username(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        username: str,
    ) -> TelegramProfile:
        """Update the authenticated account's Telegram username."""
        self._validate_account_id(account_id)

        username = username.strip()

        if not (
            MIN_USERNAME_LENGTH
            <= len(username)
            <= MAX_USERNAME_LENGTH
        ):
            raise ValueError(
                "Username must contain between "
                f"{MIN_USERNAME_LENGTH} and "
                f"{MAX_USERNAME_LENGTH} characters."
            )

        if not re.fullmatch(
            r"[A-Za-z0-9_]+",
            username,
        ):
            raise ValueError(
                "Username may contain only letters, numbers and underscores."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            await client(
                functions.account.UpdateUsernameRequest(
                    username=username,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_username_update_flood_wait",
                account_id=account_id,
            )
            raise

        except UsernameInvalidError:
            logger.warning(
                "telegram_username_invalid",
                account_id=account_id,
            )
            raise

        logger.info(
            "telegram_username_updated",
            account_id=account_id,
        )

        return await self.get_profile(
            account_id,
            api_id,
            api_hash,
        )

    async def _get_authorized_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Retrieve an authorised Telegram client."""
        self._validate_account_id(account_id)

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
    def _normalise_profile(
        account_id: int,
        user: types.User,
        about: str | None,
    ) -> TelegramProfile:
        """Convert a Telethon user into a normalised profile."""
        return TelegramProfile(
            account_id=account_id,
            user_id=user.id,
            first_name=user.first_name or "",
            last_name=user.last_name,
            username=user.username,
            phone=user.phone,
            about=about,
            verified=bool(user.verified),
            premium=bool(user.premium),
            bot=bool(user.bot),
            scam=bool(user.scam),
            fake=bool(user.fake),
            restricted=bool(user.restricted),
        )

    @staticmethod
    def _validate_account_id(account_id: int) -> None:
        if account_id <= 0:
            raise ValueError(
                "account_id must be positive."
            )
