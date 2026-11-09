"""
Telegram permissions service.

Retrieves and normalises chat-level and participant-level permissions
using Telethon.
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
    UserNotParticipantError,
)

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramPermissionInfo:
    """Normalised permissions for a Telegram participant."""

    chat_id: int
    user_id: int | None
    participant_status: str | None
    is_admin: bool
    is_creator: bool
    is_banned: bool
    is_restricted: bool

    can_send_messages: bool | None
    can_send_media: bool | None
    can_send_polls: bool | None
    can_send_other_messages: bool | None
    can_add_web_page_previews: bool | None
    can_change_info: bool | None
    can_invite_users: bool | None
    can_pin_messages: bool | None
    can_manage_topics: bool | None

    can_delete_messages: bool | None
    can_edit_messages: bool | None
    can_ban_users: bool | None
    can_invite_users_admin: bool | None
    can_restrict_members: bool | None
    can_promote_members: bool | None
    can_manage_call: bool | None
    can_post_messages: bool | None
    can_edit_stories: bool | None
    can_delete_stories: bool | None

    until_date: Any | None


class TelegramPermissionsService:
    """Retrieve Telegram chat and participant permissions."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def get_my_chat_permissions(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> TelegramPermissionInfo:
        """
        Retrieve the current Telegram account's permissions in a chat.

        Raises:
            LookupError: If the current account is not a participant.
            PermissionError: If the account is not authorised.
        """
        self._validate_chat_id(chat_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            permissions = await client.get_permissions(
                chat_id,
                "me",
            )
        except UserNotParticipantError as exc:
            raise LookupError(
                "The Telegram account is not a participant in this chat."
            ) from exc
        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
        ):
            raise

        return self._normalise_permissions(
            permissions=permissions,
            chat_id=chat_id,
            user_id=None,
        )

    async def get_participant_permissions(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        user_id: int,
    ) -> TelegramPermissionInfo:
        """
        Retrieve a participant's effective permissions in a chat.

        The Telegram account must have sufficient access to inspect
        the requested participant.
        """
        self._validate_chat_id(chat_id)

        if user_id <= 0:
            raise ValueError("user_id must be positive.")

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            permissions = await client.get_permissions(
                chat_id,
                user_id,
            )
        except UserNotParticipantError as exc:
            raise LookupError(
                "The requested user is not a participant in this chat."
            ) from exc
        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
            UserIdInvalidError,
        ):
            raise

        return self._normalise_permissions(
            permissions=permissions,
            chat_id=chat_id,
            user_id=user_id,
        )

    async def can_send_messages(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> bool:
        """Check whether the current account can send text messages."""
        permissions = await self.get_my_chat_permissions(
            account_id,
            api_id,
            api_hash,
            chat_id,
        )

        return permissions.can_send_messages is True

    async def can_send_media(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> bool:
        """Check whether the current account can send media."""
        permissions = await self.get_my_chat_permissions(
            account_id,
            api_id,
            api_hash,
            chat_id,
        )

        return permissions.can_send_media is True

    async def can_manage_chat(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> bool:
        """Check whether the current account has administrative privileges."""
        permissions = await self.get_my_chat_permissions(
            account_id,
            api_id,
            api_hash,
            chat_id,
        )

        return permissions.is_admin or permissions.is_creator

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
    def _normalise_permissions(
        permissions: Any,
        chat_id: int,
        user_id: int | None,
    ) -> TelegramPermissionInfo:
        """Convert Telethon permission information into a stable schema."""
        admin_rights = getattr(permissions, "admin_rights", None)
        banned_rights = getattr(permissions, "banned_rights", None)

        participant = getattr(permissions, "participant", None)

        participant_status = (
            type(participant).__name__
            if participant is not None
            else None
        )

        is_creator = bool(
            getattr(permissions, "is_creator", False)
        )

        is_admin = bool(
            getattr(permissions, "is_admin", False)
        ) or is_creator

        is_banned = bool(
            getattr(permissions, "is_banned", False)
        )

        is_restricted = bool(
            getattr(permissions, "is_restricted", False)
        )

        def permission_value(name: str) -> bool | None:
            """Return a permission flag without inventing missing values."""
            value = getattr(permissions, name, None)

            if value is None:
                return None

            return bool(value)

        def admin_value(name: str) -> bool | None:
            """Return an administrative permission flag."""
            if admin_rights is None:
                return None

            value = getattr(admin_rights, name, None)

            if value is None:
                return None

            return bool(value)

        return TelegramPermissionInfo(
            chat_id=chat_id,
            user_id=user_id,
            participant_status=participant_status,
            is_admin=is_admin,
            is_creator=is_creator,
            is_banned=is_banned,
            is_restricted=is_restricted,

            can_send_messages=permission_value("send_messages"),
            can_send_media=permission_value("send_media"),
            can_send_polls=permission_value("send_polls"),
            can_send_other_messages=permission_value(
                "send_stickers"
            ),
            can_add_web_page_previews=permission_value(
                "embed_links"
            ),
            can_change_info=permission_value("change_info"),
            can_invite_users=permission_value("invite_users"),
            can_pin_messages=permission_value("pin_messages"),
            can_manage_topics=permission_value("manage_topics"),

            can_delete_messages=admin_value("delete_messages"),
            can_edit_messages=admin_value("edit_messages"),
            can_ban_users=admin_value("ban_users"),
            can_invite_users_admin=admin_value("invite_users"),
            can_restrict_members=admin_value("ban_users"),
            can_promote_members=admin_value("add_admins"),
            can_manage_call=admin_value("manage_call"),
            can_post_messages=admin_value("post_messages"),
            can_edit_stories=admin_value("edit_stories"),
            can_delete_stories=admin_value("delete_stories"),

            until_date=getattr(permissions, "until_date", None),
        )

    @staticmethod
    def _validate_chat_id(chat_id: int) -> None:
        """Validate a Telegram chat identifier."""
        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")
