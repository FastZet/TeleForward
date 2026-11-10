"""
Telegram media-download service.

Downloads media attached to Telegram messages into managed storage.

Features:
- Individual and batch media downloads.
- Configurable maximum file size.
- Generated filenames instead of trusting Telegram filenames.
- Storage-directory containment checks.
- Cleanup of incomplete downloads.
- Normalised download results.
"""

from __future__ import annotations

import mimetypes
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatIdInvalidError,
    FloodWaitError,
    MessageIdInvalidError,
    PeerIdInvalidError,
)
from telethon.tl.custom.message import Message

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

DEFAULT_MAX_DOWNLOAD_SIZE = 512 * 1024 * 1024
MAX_DOWNLOAD_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class TelegramDownloadResult:
    """Result of downloading Telegram media."""

    account_id: int
    chat_id: int
    message_id: int
    file_path: str
    file_name: str
    file_size: int
    mime_type: str | None
    successful: bool


@dataclass(frozen=True, slots=True)
class TelegramBatchDownloadResult:
    """Result of a batch media-download operation."""

    account_id: int
    chat_id: int
    results: tuple[TelegramDownloadResult, ...]
    successful_count: int
    failed_message_ids: tuple[int, ...]


class TelegramDownloadService:
    """Download Telegram message media into managed storage."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
        storage_dir: str | Path,
        max_download_size: int = DEFAULT_MAX_DOWNLOAD_SIZE,
    ) -> None:
        self.client_manager = client_manager
        self.storage_dir = Path(storage_dir).expanduser().resolve()
        self.max_download_size = max_download_size

        if max_download_size <= 0:
            raise ValueError(
                "max_download_size must be positive."
            )

        self.storage_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        if self.storage_dir.is_symlink():
            raise ValueError(
                "Download storage directory cannot be a symbolic link."
            )

    async def download_message(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
    ) -> TelegramDownloadResult:
        """Download media attached to a single Telegram message."""
        self._validate_identifiers(
            account_id,
            chat_id,
            message_id,
        )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        message = await client.get_messages(
            entity,
            ids=message_id,
        )

        if not isinstance(message, Message):
            raise ValueError(
                f"Telegram message {message_id} could not be found."
            )

        return await self._download_message(
            message=message,
            account_id=account_id,
            chat_id=chat_id,
        )

    async def download_messages(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_ids: list[int],
    ) -> TelegramBatchDownloadResult:
        """
        Download media from multiple Telegram messages.

        Individual download failures are recorded without discarding
        successfully downloaded files.
        """
        self._validate_batch(
            account_id,
            chat_id,
            message_ids,
        )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        entity = await client.get_input_entity(chat_id)

        results: list[TelegramDownloadResult] = []
        failed_ids: list[int] = []

        for start in range(
            0,
            len(message_ids),
            MAX_DOWNLOAD_BATCH_SIZE,
        ):
            batch = message_ids[
                start:start + MAX_DOWNLOAD_BATCH_SIZE
            ]

            messages = await client.get_messages(
                entity,
                ids=batch,
            )

            if not isinstance(messages, list):
                messages = [messages]

            message_by_id = {
                message.id: message
                for message in messages
                if isinstance(message, Message)
            }

            for message_id in batch:
                message = message_by_id.get(message_id)

                if message is None:
                    failed_ids.append(message_id)
                    continue

                try:
                    result = await self._download_message(
                        message=message,
                        account_id=account_id,
                        chat_id=chat_id,
                    )
                    results.append(result)

                except FloodWaitError:
                    raise

                except Exception:
                    failed_ids.append(message_id)

                    logger.exception(
                        "telegram_media_download_failed",
                        account_id=account_id,
                        chat_id=chat_id,
                        message_id=message_id,
                    )

        return TelegramBatchDownloadResult(
            account_id=account_id,
            chat_id=chat_id,
            results=tuple(results),
            successful_count=len(results),
            failed_message_ids=tuple(failed_ids),
        )

    async def _download_message(
        self,
        message: Message,
        account_id: int,
        chat_id: int,
    ) -> TelegramDownloadResult:
        """Download one message's media."""
        if message.media is None or message.file is None:
            raise ValueError(
                f"Message {message.id} has no downloadable media."
            )

        declared_size = getattr(
            message.file,
            "size",
            None,
        )

        if (
            declared_size is not None
            and declared_size > self.max_download_size
        ):
            raise ValueError(
                "Media exceeds the configured download-size limit."
            )

        extension = self._safe_extension(
            getattr(message.file, "ext", None)
        )

        generated_name = (
            f"{uuid.uuid4().hex}{extension}"
        )

        account_directory = self.storage_dir / str(account_id)

        account_directory.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        if account_directory.is_symlink():
            raise ValueError(
                "Account download directory cannot be a symbolic link."
            )

        destination = account_directory / generated_name

        resolved_destination = destination.resolve()

        if (
            resolved_destination.parent
            != account_directory.resolve()
        ):
            raise ValueError(
                "Download destination escaped the managed directory."
            )

        if destination.exists() or destination.is_symlink():
            raise FileExistsError(
                "Generated download filename already exists."
            )

        try:
            downloaded = await message.download_media(
                file=str(destination)
            )

            if downloaded is None:
                raise RuntimeError(
                    "Telegram did not return a downloaded media path."
                )

            downloaded_path = Path(downloaded).resolve()

            if downloaded_path != resolved_destination:
                raise RuntimeError(
                    "Downloaded file path does not match the expected path."
                )

            if not downloaded_path.is_file():
                raise RuntimeError(
                    "Downloaded media is not a regular file."
                )

            file_size = downloaded_path.stat().st_size

            if file_size <= 0:
                raise RuntimeError(
                    "Downloaded media file is empty."
                )

            if file_size > self.max_download_size:
                raise ValueError(
                    "Downloaded media exceeds the configured size limit."
                )

            mime_type = (
                getattr(message.file, "mime_type", None)
                or mimetypes.guess_type(generated_name)[0]
            )

            result = TelegramDownloadResult(
                account_id=account_id,
                chat_id=chat_id,
                message_id=message.id,
                file_path=str(downloaded_path),
                file_name=generated_name,
                file_size=file_size,
                mime_type=mime_type,
                successful=True,
            )

            logger.info(
                "telegram_media_downloaded",
                account_id=account_id,
                chat_id=chat_id,
                message_id=message.id,
                file_size=file_size,
            )

            return result

        except Exception:
            self._remove_incomplete_file(destination)
            raise

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
    def _safe_extension(
        extension: str | None,
    ) -> str:
        """Accept only conventional file extensions."""
        if not extension:
            return ""

        extension = extension.lower()

        if not re.fullmatch(
            r"\.[a-z0-9]{1,10}",
            extension,
        ):
            return ""

        return extension

    @staticmethod
    def _remove_incomplete_file(
        path: Path,
    ) -> None:
        """Remove an incomplete download if it exists."""
        try:
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
        except OSError:
            logger.exception(
                "telegram_incomplete_download_cleanup_failed",
                path=str(path),
            )

    @staticmethod
    def _validate_identifiers(
        account_id: int,
        chat_id: int,
        message_id: int,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

        if message_id <= 0:
            raise ValueError("message_id must be positive.")

    @staticmethod
    def _validate_batch(
        account_id: int,
        chat_id: int,
        message_ids: list[int],
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

        if not message_ids:
            raise ValueError("At least one message ID is required.")

        if len(message_ids) > 10_000:
            raise ValueError(
                "A maximum of 10,000 message IDs can be submitted."
            )

        if any(message_id <= 0 for message_id in message_ids):
            raise ValueError("All message IDs must be positive.")

        if len(set(message_ids)) != len(message_ids):
            raise ValueError("Duplicate message IDs are not allowed.")
