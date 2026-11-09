"""
Telegram participant service.

Provides participant listing, lookup, and normalised membership
information through Telethon.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatIdInvalidError,
    UserIdInvalidError,
)
from telethon.tl.types import User

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

DEFAULT_PARTICIPANT_LIMIT = 100
MAX_PARTICIPANT_LIMIT = 500


@dataclass(frozen=True, slots=True)
class TelegramParticipant:
    """Normalised Telegram participant information."""

    user_id: int
    access_hash: int | None
    first_name: str | None
    last_name: str | None
    username: str | None
    phone: str | None
    display_name: str | None

    is_bot: bool
    is_verified: bool
    is_premium: bool
    is_scam: bool
    is_fake: bool
    is_deleted: bool

    participant_status: str | None
    is_admin: bool
    is_creator: bool
    is_restricted: bool
    is_banned: bool

    joined_date: Any | None
    until_date: Any | None


@dataclass(frozen=True, slots=True)
class TelegramParticipantPage:
    """Participant listing with pagination metadata."""

    chat_id: int
    participants: list[TelegramParticipant]
    limit: int
    has_more: bool


class TelegramParticipantService:
    """Retrieve and normalise Telegram chat participants."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def list_participants(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        *,
        limit: int = DEFAULT_PARTICIPANT_LIMIT,
        search: str | None = None,
    ) -> TelegramParticipantPage:
        """
        Retrieve participants from a Telegram chat.

        The service fetches one additional participant to determine
        whether more results are available.

        Note:
            This is a bounded first-page listing. It does not expose
            Telegram's internal participant offsets as stable cursors.
        """
        self._validate_chat_id(chat_id)
        self._validate_limit(limit)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        normalised_search = self._normalise_search(search)

        try:
            users = await client.get_participants(
                chat_id,
                limit=limit + 1,
                search=normalised_search,
            )
        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
        ):
            raise

        has_more = len(users) > limit
        selected_users = users[:limit]

        participants = [
            self._normalise_participant(user)
            for user in selected_users
            if isinstance(user, User)
        ]

        logger.debug(
            "telegram_participants_listed",
            account_id=account_id,
            chat_id=chat_id,
            result_count=len(participants),
            has_more=has_more,
        )

        return TelegramParticipantPage(
            chat_id=chat_id,
            participants=participants,
            limit=limit,
            has_more=has_more,
        )

    async def get_participant(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        user_id: int,
    ) -> TelegramParticipant | None:
        """Retrieve a specific participant from a Telegram chat."""
        self._validate_chat_id(chat_id)

        if user_id <= 0:
            raise ValueError("user_id must be positive.")

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            user = await client.get_entity(user_id)

            if not isinstance(user, User):
                return None

            participant = await client.get_permissions(
                chat_id,
                user,
            )

        except UserIdInvalidError:
            return None
        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
        ):
            raise

        return self._normalise_participant(
            user,
            participant=participant,
        )

    async def count_participants(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> int:
        """
        Retrieve the participant count reported by Telegram.

        The count may be unavailable for certain chat types or
        account permission levels.
        """
        self._validate_chat_id(chat_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            full_chat = await client.get_entity(chat_id)
            full_info = await client.get_full_entity(full_chat)
        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
        ):
            raise

        chats = getattr(full_info, "full_chat", None)

        if chats is None:
            return 0

        count = getattr(chats, "participants_count", None)

        if count is None:
            return 0

        return max(0, int(count))

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
    def _normalise_participant(
        user: User,
        participant: Any | None = None,
    ) -> TelegramParticipant:
        """Convert a Telethon User into the application representation."""
        membership = participant or getattr(user, "participant", None)

        membership_name = (
            type(membership).__name__
            if membership is not None
            else None
        )

        is_creator = membership_name in {
            "ChannelParticipantCreator",
            "ChatParticipantCreator",
        }

        is_admin = is_creator or membership_name in {
            "ChannelParticipantAdmin",
            "ChatParticipantAdmin",
        }

        banned_rights = getattr(
            membership,
            "banned_rights",
            None,
        )

        is_banned = membership_name in {
            "ChannelParticipantBanned",
            "ChannelParticipantLeft",
        }

        is_restricted = (
            banned_rights is not None
            or membership_name == "ChannelParticipantBanned"
        )

        first_name = getattr(user, "first_name", None)
        last_name = getattr(user, "last_name", None)

        display_name = " ".join(
            part
            for part in (first_name, last_name)
            if part
        ) or None

        return TelegramParticipant(
            user_id=user.id,
            access_hash=getattr(user, "access_hash", None),
            first_name=first_name,
            last_name=last_name,
            username=getattr(user, "username", None),
            phone=getattr(user, "phone", None),
            display_name=display_name,

            is_bot=bool(getattr(user, "bot", False)),
            is_verified=bool(getattr(user, "verified", False)),
            is_premium=bool(getattr(user, "premium", False)),
            is_scam=bool(getattr(user, "scam", False)),
            is_fake=bool(getattr(user, "fake", False)),
            is_deleted=bool(getattr(user, "deleted", False)),

            participant_status=membership_name,
            is_admin=is_admin,
            is_creator=is_creator,
            is_restricted=is_restricted,
            is_banned=is_banned,

            joined_date=getattr(membership, "date", None),
            until_date=getattr(membership, "until_date", None),
        )

    @staticmethod
    def _normalise_search(search: str | None) -> str | None:
        """Normalise a participant search string."""
        if search is None:
            return None

        value = search.strip()

        if not value:
            return None

        if len(value) > 128:
            raise ValueError("Participant search is too long.")

        return value

    @staticmethod
    def _validate_chat_id(chat_id: int) -> None:
        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not 1 <= limit <= MAX_PARTICIPANT_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {MAX_PARTICIPANT_LIMIT}."
            )
