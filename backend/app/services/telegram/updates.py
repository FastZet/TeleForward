"""
Telegram updates service.

Registers Telethon event handlers and forwards normalised Telegram
updates to application callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

import structlog
from telethon import TelegramClient, events
from telethon.tl.custom.message import Message

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

UpdateType = Literal[
    "new_message",
    "message_edited",
    "message_deleted",
    "album",
]

UpdateCallback = Callable[
    ["TelegramUpdate"],
    Awaitable[None],
]


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    """Normalised representation of a Telegram update."""

    account_id: int
    update_type: UpdateType
    chat_id: int | None
    message_id: int | None
    message_ids: tuple[int, ...]
    message: Message | None
    grouped_id: int | None


@dataclass(slots=True)
class RegisteredHandlers:
    """References required to unregister an account's event handlers."""

    account_id: int
    client: TelegramClient
    handlers: list[tuple[Callable, object]]


class TelegramUpdatesService:
    """Manage Telegram event subscriptions."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager
        self._registered: dict[int, RegisteredHandlers] = {}

    async def register_handlers(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        callback: UpdateCallback,
        *,
        chats: list[int] | None = None,
    ) -> None:
        """
        Register event handlers for a Telegram account.

        Registering handlers more than once for the same account
        replaces the existing registrations.

        Args:
            account_id: Internal Telegram account identifier.
            api_id: Telegram API application ID.
            api_hash: Telegram API application hash.
            callback: Async application callback receiving TelegramUpdate.
            chats: Optional Telegram chat IDs to monitor. None monitors
                all chats accessible to the account.
        """
        self._validate_account_id(account_id)

        if not callable(callback):
            raise ValueError("callback must be callable.")

        if chats is not None:
            if not chats:
                raise ValueError(
                    "chats must contain at least one chat ID or be None."
                )

            if any(chat_id == 0 for chat_id in chats):
                raise ValueError("Chat IDs cannot be zero.")

        await self.unregister_handlers(account_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        handlers: list[tuple[Callable, object]] = []

        event_builders = [
            (
                "new_message",
                events.NewMessage(chats=chats),
            ),
            (
                "message_edited",
                events.MessageEdited(chats=chats),
            ),
            (
                "message_deleted",
                events.MessageDeleted(chats=chats),
            ),
            (
                "album",
                events.Album(chats=chats),
            ),
        ]

        for update_type, event_builder in event_builders:

            async def handler(
                event: object,
                current_type: UpdateType = update_type,
            ) -> None:
                update = self._normalise_event(
                    account_id=account_id,
                    update_type=current_type,
                    event=event,
                )

                if update is None:
                    return

                try:
                    await callback(update)

                except Exception:
                    logger.exception(
                        "telegram_update_callback_failed",
                        account_id=account_id,
                        update_type=current_type,
                        chat_id=update.chat_id,
                        message_id=update.message_id,
                    )

            client.add_event_handler(
                handler,
                event_builder,
            )

            handlers.append((handler, event_builder))

        self._registered[account_id] = RegisteredHandlers(
            account_id=account_id,
            client=client,
            handlers=handlers,
        )

        logger.info(
            "telegram_update_handlers_registered",
            account_id=account_id,
            monitored_chats=len(chats) if chats else None,
            handler_count=len(handlers),
        )

    async def unregister_handlers(
        self,
        account_id: int,
    ) -> bool:
        """
        Remove all event handlers registered for an account.

        Returns:
            True if registrations existed and were removed.
        """
        self._validate_account_id(account_id)

        registration = self._registered.pop(account_id, None)

        if registration is None:
            return False

        for handler, event_builder in registration.handlers:
            registration.client.remove_event_handler(
                handler,
                event_builder,
            )

        logger.info(
            "telegram_update_handlers_unregistered",
            account_id=account_id,
        )

        return True

    async def unregister_all(self) -> int:
        """Remove all handlers managed by this service."""
        account_ids = list(self._registered)

        for account_id in account_ids:
            await self.unregister_handlers(account_id)

        return len(account_ids)

    def is_registered(self, account_id: int) -> bool:
        """Check whether an account has registered event handlers."""
        return account_id in self._registered

    async def _get_authorized_client(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramClient:
        """Retrieve a connected and authorised Telegram client."""
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
    def _normalise_event(
        account_id: int,
        update_type: UpdateType,
        event: object,
    ) -> TelegramUpdate | None:
        """Convert a Telethon event into a TelegramUpdate."""
        chat_id = getattr(event, "chat_id", None)

        if update_type == "message_deleted":
            deleted_ids = getattr(event, "deleted_ids", None)

            if not deleted_ids:
                return None

            message_ids = tuple(
                int(message_id)
                for message_id in deleted_ids
            )

            return TelegramUpdate(
                account_id=account_id,
                update_type=update_type,
                chat_id=chat_id,
                message_id=None,
                message_ids=message_ids,
                message=None,
                grouped_id=None,
            )

        if update_type == "album":
            messages = getattr(event, "messages", None) or []

            if not messages:
                return None

            message_ids = tuple(
                message.id
                for message in messages
                if getattr(message, "id", None) is not None
            )

            first_message = messages[0]

            return TelegramUpdate(
                account_id=account_id,
                update_type=update_type,
                chat_id=chat_id,
                message_id=first_message.id,
                message_ids=message_ids,
                message=first_message,
                grouped_id=getattr(first_message, "grouped_id", None),
            )

        message = getattr(event, "message", None)

        if message is None:
            return None

        message_id = getattr(message, "id", None)

        if message_id is None:
            return None

        return TelegramUpdate(
            account_id=account_id,
            update_type=update_type,
            chat_id=chat_id,
            message_id=message_id,
            message_ids=(message_id,),
            message=message,
            grouped_id=getattr(message, "grouped_id", None),
        )

    @staticmethod
    def _validate_account_id(account_id: int) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")
