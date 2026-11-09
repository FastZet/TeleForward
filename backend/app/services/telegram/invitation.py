"""
Telegram invitation service.

Provides invitation-link management and participant invitations
through Telethon.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

import structlog
from telethon import TelegramClient, functions, types
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatIdInvalidError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    UserAlreadyParticipantError,
    UserIdInvalidError,
)

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

MAX_INVITE_USERS = 100


@dataclass(frozen=True, slots=True)
class TelegramInviteLink:
    """Normalised Telegram invitation-link information."""

    link: str
    is_primary: bool
    is_revoked: bool
    is_expired: bool
    expiration_date: datetime | None
    usage_limit: int | None
    usage_count: int | None
    request_needed: bool
    title: str | None


@dataclass(frozen=True, slots=True)
class TelegramInvitationResult:
    """Result of a participant invitation operation."""

    chat_id: int
    invited_user_ids: list[int]
    already_participants: list[int]
    failed_user_ids: list[int]


class TelegramInvitationService:
    """Create and manage Telegram invitations."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def create_invite_link(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        *,
        expiration_date: datetime | None = None,
        usage_limit: int | None = None,
        request_needed: bool = False,
        title: str | None = None,
    ) -> TelegramInviteLink:
        """
        Create a new Telegram invitation link.

        The requesting account must have permission to manage
        invitation links in the target chat.
        """
        self._validate_chat_id(chat_id)
        self._validate_invite_options(
            expiration_date,
            usage_limit,
            title,
        )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_entity(chat_id)

        try:
            result = await client(
                functions.messages.ExportChatInviteRequest(
                    peer=entity,
                    expire_date=expiration_date,
                    usage_limit=usage_limit,
                    request_needed=request_needed,
                    title=title,
                )
            )
        except (
            ChannelInvalidError,
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
        ):
            raise

        invite = self._normalise_invite_link(result)

        logger.info(
            "telegram_invite_link_created",
            account_id=account_id,
            chat_id=chat_id,
            usage_limit=usage_limit,
            request_needed=request_needed,
        )

        return invite

    async def revoke_invite_link(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        invite_link: str,
    ) -> TelegramInviteLink:
        """Revoke an existing Telegram invitation link."""
        self._validate_chat_id(chat_id)

        if not invite_link or len(invite_link) > 2048:
            raise ValueError("A valid invitation link is required.")

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_entity(chat_id)

        try:
            result = await client(
                functions.messages.RevokeChatInviteRequest(
                    peer=entity,
                    link=invite_link,
                )
            )
        except (
            ChannelInvalidError,
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
        ):
            raise

        invite = self._normalise_invite_link(result)

        logger.info(
            "telegram_invite_link_revoked",
            account_id=account_id,
            chat_id=chat_id,
        )

        return invite

    async def invite_participants(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        user_ids: Sequence[int],
    ) -> TelegramInvitationResult:
        """
        Invite users to a Telegram channel or supergroup.

        This method deliberately does not silently skip invalid users.
        User resolution failures are reported as failed invitations.
        """
        self._validate_chat_id(chat_id)

        if not user_ids:
            raise ValueError("At least one user ID is required.")

        if len(user_ids) > MAX_INVITE_USERS:
            raise ValueError(
                f"A maximum of {MAX_INVITE_USERS} users can be "
                "processed per request."
            )

        if any(user_id <= 0 for user_id in user_ids):
            raise ValueError("All user IDs must be positive.")

        if len(set(user_ids)) != len(user_ids):
            raise ValueError("Duplicate user IDs are not allowed.")

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_entity(chat_id)

        if not isinstance(entity, types.Channel):
            raise ValueError(
                "Participant invitations through this method require "
                "a channel or supergroup."
            )

        resolved_users: list[types.InputUser] = []
        failed_user_ids: list[int] = []

        for user_id in user_ids:
            try:
                user = await client.get_input_entity(user_id)

                if not isinstance(user, types.InputUser):
                    failed_user_ids.append(user_id)
                    continue

                resolved_users.append(user)

            except (ValueError, UserIdInvalidError):
                failed_user_ids.append(user_id)

        invited_user_ids: list[int] = []
        already_participants: list[int] = []

        if resolved_users:
            try:
                await client(
                    functions.channels.InviteToChannelRequest(
                        channel=entity,
                        users=resolved_users,
                    )
                )

                invited_user_ids = [
                    user_id
                    for user_id in user_ids
                    if user_id not in failed_user_ids
                ]

            except UserAlreadyParticipantError:
                # Telegram may report this for a batch operation.
                # Resolve individual membership to distinguish users.
                for user_id in user_ids:
                    if user_id in failed_user_ids:
                        continue

                    try:
                        await client(
                            functions.channels.InviteToChannelRequest(
                                channel=entity,
                                users=[
                                    await client.get_input_entity(user_id)
                                ],
                            )
                        )
                        invited_user_ids.append(user_id)

                    except UserAlreadyParticipantError:
                        already_participants.append(user_id)

                    except Exception:
                        failed_user_ids.append(user_id)

            except (
                ChannelInvalidError,
                ChannelPrivateError,
                ChatAdminRequiredError,
                ChatIdInvalidError,
            ):
                raise

            except Exception:
                logger.exception(
                    "telegram_participant_invitation_failed",
                    account_id=account_id,
                    chat_id=chat_id,
                )
                raise

        logger.info(
            "telegram_participants_invited",
            account_id=account_id,
            chat_id=chat_id,
            invited_count=len(invited_user_ids),
            already_participant_count=len(already_participants),
            failed_count=len(failed_user_ids),
        )

        return TelegramInvitationResult(
            chat_id=chat_id,
            invited_user_ids=invited_user_ids,
            already_participants=already_participants,
            failed_user_ids=failed_user_ids,
        )

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
    def _normalise_invite_link(result: object) -> TelegramInviteLink:
        """Convert a Telethon invite-link response into a stable structure."""
        return TelegramInviteLink(
            link=getattr(result, "link", ""),
            is_primary=bool(
                getattr(result, "is_primary", False)
            ),
            is_revoked=bool(
                getattr(result, "revoked", False)
            ),
            is_expired=bool(
                getattr(result, "expired", False)
            ),
            expiration_date=getattr(result, "expire_date", None),
            usage_limit=getattr(result, "usage_limit", None),
            usage_count=getattr(result, "usage", None),
            request_needed=bool(
                getattr(result, "request_needed", False)
            ),
            title=getattr(result, "title", None),
        )

    @staticmethod
    def _validate_chat_id(chat_id: int) -> None:
        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

    @staticmethod
    def _validate_invite_options(
        expiration_date: datetime | None,
        usage_limit: int | None,
        title: str | None,
    ) -> None:
        if expiration_date is not None:
            if expiration_date.tzinfo is None:
                raise ValueError(
                    "expiration_date must be timezone-aware."
                )

            if expiration_date.utcoffset() is None:
                raise ValueError(
                    "expiration_date must have a valid timezone."
                )

        if usage_limit is not None and usage_limit <= 0:
            raise ValueError("usage_limit must be positive.")

        if title is not None:
            title = title.strip()

            if not title or len(title) > 32:
                raise ValueError(
                    "Invitation title must contain 1–32 characters."
                )
