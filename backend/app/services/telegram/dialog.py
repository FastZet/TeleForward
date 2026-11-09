"""
Telegram dialog service.

Retrieves Telegram dialogs and exposes a normalised representation
for application services and API endpoints.

This service does not persist chat records. Synchronisation and
database persistence are handled by the chat management service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import structlog
from telethon import TelegramClient
from telethon.tl.custom.dialog import Dialog

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

DialogType = Literal["private", "group", "supergroup", "channel", "unknown"]


@dataclass(frozen=True, slots=True)
class TelegramDialog:
    """Normalised representation of a Telegram dialog."""

    chat_id: int
    title: str
    dialog_type: DialogType
    username: str | None
    unread_count: int
    is_pinned: bool
    is_archived: bool
    last_message_id: int | None
    last_message_date: datetime | None


class TelegramDialogService:
    """Retrieve and filter dialogs belonging to Telegram accounts."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def list_dialogs(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        limit: int | None = 100,
        archived: bool | None = None,
        search: str | None = None,
    ) -> list[TelegramDialog]:
        """
        Retrieve dialogs for a Telegram account.

        Args:
            account_id: Internal TeleForward account ID.
            api_id: Telegram application API ID.
            api_hash: Telegram application API hash.
            limit: Maximum number of dialogs to retrieve. None means
                retrieve all available dialogs.
            archived: True for archived dialogs, False for active
                dialogs, or None for both.
            search: Optional case-insensitive title or username filter.

        Returns:
            A list of normalised Telegram dialogs.
        """
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive or None.")

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

        search_term = search.strip().casefold() if search else None

        dialogs: list[TelegramDialog] = []

        async for dialog in client.iter_dialogs(limit=limit):
            normalised = self._normalise_dialog(dialog)

            if archived is not None:
                if normalised.is_archived != archived:
                    continue

            if search_term:
                searchable = " ".join(
                    filter(
                        None,
                        (
                            normalised.title,
                            normalised.username,
                        ),
                    )
                ).casefold()

                if search_term not in searchable:
                    continue

            dialogs.append(normalised)

        logger.info(
            "telegram_dialogs_retrieved",
            account_id=account_id,
            count=len(dialogs),
            archived_filter=archived,
        )

        return dialogs

    async def get_dialog(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
    ) -> TelegramDialog | None:
        """
        Retrieve a specific dialog by its Telegram chat ID.

        Returns None if the dialog is not found in the account's dialogs.
        """
        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

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

        try:
            entity = await client.get_entity(chat_id)
            input_entity = await client.get_input_entity(entity)
            dialog = await client.get_dialogs(limit=1, folder=None)

            for item in dialog:
                if item.id == chat_id:
                    return self._normalise_dialog(item)

            # The entity exists, but it is not necessarily an existing dialog.
            return None

        except ValueError:
            return None

    @staticmethod
    def _normalise_dialog(dialog: Dialog) -> TelegramDialog:
        """Convert a Telethon dialog into the application representation."""
        entity = dialog.entity

        if dialog.is_user:
            dialog_type: DialogType = "private"
        elif dialog.is_group:
            dialog_type = (
                "supergroup"
                if getattr(entity, "megagroup", False)
                else "group"
            )
        elif dialog.is_channel:
            dialog_type = "channel"
        else:
            dialog_type = "unknown"

        username = getattr(entity, "username", None)
        message = dialog.message

        return TelegramDialog(
            chat_id=dialog.id,
            title=dialog.title or str(dialog.id),
            dialog_type=dialog_type,
            username=username,
            unread_count=dialog.unread_count,
            is_pinned=bool(dialog.pinned),
            is_archived=dialog.folder_id == 1,
            last_message_id=(
                message.id if message is not None else None
            ),
            last_message_date=(
                message.date if message is not None else None
            ),
        )
