"""
Telegram notification service.

Supports:
- Sending text notifications.
- Sending media notifications.
- Sending notifications with inline buttons.
- Sending notifications silently.
- Sending notifications with formatting.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import structlog
from telethon import TelegramClient, Button
from telethon.errors import FloodWaitError

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

MAX_NOTIFICATION_LENGTH = 4096
MAX_BUTTONS = 100
MAX_BUTTON_TEXT_LENGTH = 64


@dataclass(frozen=True, slots=True)
class TelegramNotificationResult:
    """Result of a Telegram notification operation."""

    account_id: int
    destination: str
    successful: bool
    message_ids: tuple[int, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramInlineButton:
    """Inline keyboard button definition."""

    text: str
    url: str | None = None
    callback_data: bytes | str | None = None


class TelegramNotificationService:
    """Send notifications through Telegram accounts."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
    ) -> None:
        self.client_manager = client_manager

    async def send_text(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        destination: int | str,
        message: str,
        *,
        parse_mode: str | None = "html",
        silent: bool = False,
        link_preview: bool = True,
        reply_to: int | None = None,
    ) -> TelegramNotificationResult:
        """Send a text notification."""
        if not message or not message.strip():
            raise ValueError(
                "Notification message cannot be empty."
            )

        if len(message) > MAX_NOTIFICATION_LENGTH:
            raise ValueError(
                f"Notification cannot exceed {MAX_NOTIFICATION_LENGTH} characters."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            sent_message = await client.send_message(
                entity=destination,
                message=message,
                parse_mode=parse_mode,
                silent=silent,
                link_preview=link_preview,
                reply_to=reply_to,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_notification_flood_wait",
                account_id=account_id,
            )
            raise

        except Exception:
            logger.exception(
                "telegram_notification_send_failed",
                account_id=account_id,
            )
            raise

        message_id = getattr(
            sent_message,
            "id",
            None,
        )

        logger.info(
            "telegram_notification_sent",
            account_id=account_id,
            message_id=message_id,
        )

        return TelegramNotificationResult(
            account_id=account_id,
            destination=str(destination),
            successful=True,
            message_ids=(
                (message_id,)
                if message_id is not None
                else ()
            ),
        )

    async def send_media(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        destination: int | str,
        media_path: str | Path,
        *,
        caption: str | None = None,
        parse_mode: str | None = "html",
        silent: bool = False,
        force_document: bool = False,
        reply_to: int | None = None,
    ) -> TelegramNotificationResult:
        """Send a media notification from a local file."""
        path = Path(media_path).expanduser().resolve(
            strict=True
        )

        if not path.is_file():
            raise ValueError(
                "Media path must reference a regular file."
            )

        if caption and len(caption) > MAX_NOTIFICATION_LENGTH:
            raise ValueError(
                "Caption exceeds Telegram's message length limit."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            sent_messages = await client.send_file(
                entity=destination,
                file=str(path),
                caption=caption,
                parse_mode=parse_mode,
                silent=silent,
                force_document=force_document,
                reply_to=reply_to,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_media_notification_flood_wait",
                account_id=account_id,
            )
            raise

        except Exception:
            logger.exception(
                "telegram_media_notification_failed",
                account_id=account_id,
            )
            raise

        if not isinstance(sent_messages, list):
            sent_messages = [sent_messages]

        message_ids = tuple(
            message.id
            for message in sent_messages
            if getattr(message, "id", None) is not None
        )

        logger.info(
            "telegram_media_notification_sent",
            account_id=account_id,
            message_count=len(message_ids),
        )

        return TelegramNotificationResult(
            account_id=account_id,
            destination=str(destination),
            successful=bool(message_ids),
            message_ids=message_ids,
        )

    async def send_with_buttons(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        destination: int | str,
        message: str,
        buttons: Sequence[Sequence[TelegramInlineButton]],
        *,
        parse_mode: str | None = "html",
        silent: bool = False,
    ) -> TelegramNotificationResult:
        """Send a notification with an inline keyboard."""
        if not message or not message.strip():
            raise ValueError(
                "Notification message cannot be empty."
            )

        if len(message) > MAX_NOTIFICATION_LENGTH:
            raise ValueError(
                "Notification message exceeds Telegram's message length limit."
            )

        total_buttons = sum(
            len(row)
            for row in buttons
        )

        if total_buttons > MAX_BUTTONS:
            raise ValueError(
                f"A maximum of {MAX_BUTTONS} buttons is supported."
            )

        if any(not row for row in buttons):
            raise ValueError(
                "Inline keyboard rows cannot be empty."
            )

        keyboard: list[list[Any]] = []

        for row in buttons:
            keyboard_row = []

            for button in row:
                text = button.text.strip()

                if not text:
                    raise ValueError(
                        "Button text cannot be empty."
                    )

                if len(text) > MAX_BUTTON_TEXT_LENGTH:
                    raise ValueError(
                        "Button text exceeds the supported length."
                    )

                if bool(button.url) == bool(button.callback_data):
                    raise ValueError(
                        "Each button must have exactly one of URL or callback_data."
                    )

                if button.url:
                    if not button.url.startswith(
                        ("https://", "http://", "tg://")
                    ):
                        raise ValueError(
                            "Button URL must use HTTP, HTTPS or Telegram's tg scheme."
                        )

                    keyboard_row.append(
                        Button.url(text, button.url)
                    )

                else:
                    callback_data = button.callback_data

                    if isinstance(callback_data, str):
                        callback_data = callback_data.encode("utf-8")

                    if not isinstance(callback_data, bytes):
                        raise ValueError(
                            "callback_data must be bytes or a string."
                        )

                    if not 1 <= len(callback_data) <= 64:
                        raise ValueError(
                            "Callback data must contain between 1 and 64 bytes."
                        )

                    keyboard_row.append(
                        Button.inline(
                            text,
                            data=callback_data,
                        )
                    )

            keyboard.append(keyboard_row)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            sent_message = await client.send_message(
                entity=destination,
                message=message,
                buttons=keyboard,
                parse_mode=parse_mode,
                silent=silent,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_button_notification_flood_wait",
                account_id=account_id,
            )
            raise

        except Exception:
            logger.exception(
                "telegram_button_notification_failed",
                account_id=account_id,
            )
            raise

        message_id = getattr(
            sent_message,
            "id",
            None,
        )

        logger.info(
            "telegram_button_notification_sent",
            account_id=account_id,
            message_id=message_id,
            button_count=total_buttons,
        )

        return TelegramNotificationResult(
            account_id=account_id,
            destination=str(destination),
            successful=True,
            message_ids=(
                (message_id,)
                if message_id is not None
                else ()
            ),
        )

    async def delete_notification(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        destination: int | str,
        message_ids: Sequence[int],
        *,
        revoke: bool = True,
    ) -> bool:
        """Delete previously sent notification messages."""
        if not message_ids:
            raise ValueError(
                "At least one message ID is required."
            )

        if len(message_ids) > 100:
            raise ValueError(
                "A maximum of 100 message IDs can be deleted per request."
            )

        if any(message_id <= 0 for message_id in message_ids):
            raise ValueError(
                "Message IDs must be positive."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            await client.delete_messages(
                entity=destination,
                message_ids=list(dict.fromkeys(message_ids)),
                revoke=revoke,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_notification_delete_flood_wait",
                account_id=account_id,
            )
            raise

        logger.info(
            "telegram_notifications_deleted",
            account_id=account_id,
            message_count=len(set(message_ids)),
        )

        return True

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
