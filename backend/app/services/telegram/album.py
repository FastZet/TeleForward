"""
Telegram media-album copying service.

Downloads grouped source media into a temporary directory and
re-uploads it as a Telegram album.

Temporary files are automatically removed after the operation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

import structlog
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatIdInvalidError,
    FloodWaitError,
    MessageIdInvalidError,
    PeerIdInvalidError,
)
from telethon.tl.custom.message import Message

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

MAX_ALBUM_SIZE = 10
DEFAULT_MAX_ALBUM_SIZE_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TelegramAlbumCopyResult:
    """Result of copying a Telegram media album."""

    account_id: int
    source_chat_id: int
    destination_chat_id: int
    grouped_id: int
    source_message_ids: tuple[int, ...]
    destination_message_ids: tuple[int, ...]
    successful: bool


class TelegramAlbumService:
    """Copy Telegram grouped media messages as albums."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
        storage_dir: str | Path,
        max_album_size_bytes: int = DEFAULT_MAX_ALBUM_SIZE_BYTES,
    ) -> None:
        self.client_manager = client_manager
        self.storage_dir = Path(storage_dir).expanduser().resolve()
        self.max_album_size_bytes = max_album_size_bytes

        if max_album_size_bytes <= 0:
            raise ValueError(
                "max_album_size_bytes must be positive."
            )

        self.storage_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        if self.storage_dir.is_symlink():
            raise ValueError(
                "Album storage directory cannot be a symbolic link."
            )

    async def copy_album(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        source_chat_id: int,
        destination_chat_id: int,
        message_ids: Sequence[int],
        *,
        silent: bool = False,
        formatting_entities: bool = True,
    ) -> TelegramAlbumCopyResult:
        """
        Copy a grouped media album.

        The supplied message IDs must belong to one Telegram album.
        Their order is preserved according to the supplied sequence.
        """
        self._validate_identifiers(
            account_id,
            source_chat_id,
            destination_chat_id,
        )
        self._validate_message_ids(message_ids)

        if len(message_ids) > MAX_ALBUM_SIZE:
            raise ValueError(
                f"Telegram albums cannot contain more than "
                f"{MAX_ALBUM_SIZE} messages."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        source = await client.get_input_entity(source_chat_id)
        destination = await client.get_input_entity(
            destination_chat_id
        )

        requested_ids = list(message_ids)

        messages = await client.get_messages(
            source,
            ids=requested_ids,
        )

        if not isinstance(messages, list):
            messages = [messages]

        message_by_id = {
            message.id: message
            for message in messages
            if isinstance(message, Message)
        }

        ordered_messages: list[Message] = []

        for message_id in requested_ids:
            message = message_by_id.get(message_id)

            if message is None:
                raise ValueError(
                    f"Source message {message_id} could not be found."
                )

            if message.action is not None:
                raise ValueError(
                    f"Message {message_id} is a service message."
                )

            if message.grouped_id is None:
                raise ValueError(
                    f"Message {message_id} does not belong to an album."
                )

            ordered_messages.append(message)

        grouped_ids = {
            message.grouped_id
            for message in ordered_messages
        }

        if len(grouped_ids) != 1:
            raise ValueError(
                "All messages must belong to the same album."
            )

        grouped_id = next(iter(grouped_ids))

        total_size = self._validate_media_sizes(
            ordered_messages
        )

        if total_size > self.max_album_size_bytes:
            raise ValueError(
                "Album exceeds the configured maximum size."
            )

        try:
            with TemporaryDirectory(
                prefix=".telegram-album-",
                dir=self.storage_dir,
            ) as temporary_directory:
                temporary_path = Path(temporary_directory)

                downloaded_files = await self._download_album(
                    ordered_messages,
                    temporary_path,
                )

                self._verify_downloaded_size(
                    downloaded_files,
                    self.max_album_size_bytes,
                )

                captions = [
                    message.message or None
                    for message in ordered_messages
                ]

                entities = (
                    [
                        message.entities
                        for message in ordered_messages
                    ]
                    if formatting_entities
                    else None
                )

                copied_messages = await client.send_file(
                    destination,
                    file=downloaded_files,
                    caption=captions,
                    formatting_entities=entities,
                    silent=silent,
                    parse_mode=None,
                )

        except FloodWaitError:
            logger.warning(
                "telegram_album_copy_flood_wait",
                account_id=account_id,
                source_chat_id=source_chat_id,
                destination_chat_id=destination_chat_id,
                grouped_id=grouped_id,
            )
            raise

        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
            MessageIdInvalidError,
            PeerIdInvalidError,
        ):
            logger.exception(
                "telegram_album_copy_failed",
                account_id=account_id,
                source_chat_id=source_chat_id,
                destination_chat_id=destination_chat_id,
                grouped_id=grouped_id,
            )
            raise

        if not isinstance(copied_messages, list):
            copied_messages = [copied_messages]

        copied_ids = tuple(
            message.id
            for message in copied_messages
            if isinstance(message, Message)
        )

        successful = (
            len(copied_ids) == len(ordered_messages)
        )

        result = TelegramAlbumCopyResult(
            account_id=account_id,
            source_chat_id=source_chat_id,
            destination_chat_id=destination_chat_id,
            grouped_id=grouped_id,
            source_message_ids=tuple(requested_ids),
            destination_message_ids=copied_ids,
            successful=successful,
        )

        logger.info(
            "telegram_album_copied",
            account_id=account_id,
            source_chat_id=source_chat_id,
            destination_chat_id=destination_chat_id,
            grouped_id=grouped_id,
            source_message_count=len(requested_ids),
            destination_message_count=len(copied_ids),
            successful=successful,
        )

        return result

    async def _download_album(
        self,
        messages: Sequence[Message],
        temporary_path: Path,
    ) -> list[str]:
        """Download album media in the requested order."""
        downloaded_files: list[str] = []

        for index, message in enumerate(messages):
            if message.file is None:
                raise ValueError(
                    f"Album message {message.id} has no downloadable file."
                )

            suffix = self._safe_extension(
                getattr(message.file, "ext", None)
            )

            destination = (
                temporary_path / f"media-{index:02d}{suffix}"
            )

            downloaded = await message.download_media(
                file=str(destination)
            )

            if downloaded is None:
                raise RuntimeError(
                    f"Could not download album message {message.id}."
                )

            downloaded_path = Path(downloaded).resolve()

            if downloaded_path.parent != temporary_path.resolve():
                raise RuntimeError(
                    "Downloaded media escaped the temporary directory."
                )

            if not downloaded_path.is_file():
                raise RuntimeError(
                    f"Downloaded media for message {message.id} "
                    "is not a regular file."
                )

            downloaded_files.append(str(downloaded_path))

        return downloaded_files

    def _validate_media_sizes(
        self,
        messages: Sequence[Message],
    ) -> int:
        """Check declared media sizes before downloading."""
        total_size = 0

        for message in messages:
            if message.file is None:
                raise ValueError(
                    f"Message {message.id} has no downloadable media."
                )

            size = getattr(message.file, "size", None)

            if size is not None:
                if size < 0:
                    raise ValueError(
                        "Telegram returned an invalid media size."
                    )

                total_size += size

        return total_size

    @staticmethod
    def _verify_downloaded_size(
        downloaded_files: Sequence[str],
        maximum_size: int,
    ) -> None:
        """Verify actual downloaded file sizes."""
        total_size = sum(
            Path(file_path).stat().st_size
            for file_path in downloaded_files
        )

        if total_size > maximum_size:
            raise ValueError(
                "Downloaded album exceeds the configured maximum size."
            )

    @staticmethod
    def _safe_extension(extension: str | None) -> str:
        """Accept only a short, conventional file extension."""
        if not extension:
            return ""

        extension = extension.lower()

        if not re.fullmatch(r"\.[a-z0-9]{1,10}", extension):
            return ""

        return extension

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
    def _validate_identifiers(
        account_id: int,
        source_chat_id: int,
        destination_chat_id: int,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if source_chat_id == 0:
            raise ValueError("source_chat_id cannot be zero.")

        if destination_chat_id == 0:
            raise ValueError("destination_chat_id cannot be zero.")

    @staticmethod
    def _validate_message_ids(
        message_ids: Sequence[int],
    ) -> None:
        if not message_ids:
            raise ValueError("At least one message ID is required.")

        if any(message_id <= 0 for message_id in message_ids):
            raise ValueError("All message IDs must be positive.")

        if len(set(message_ids)) != len(message_ids):
            raise ValueError("Duplicate message IDs are not allowed.")
