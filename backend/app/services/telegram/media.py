"""
Telegram media service.

Provides media metadata extraction and secure downloading through
Telethon. Downloaded files are stored in the configured media directory.

Media paths must remain within the configured storage directory.
"""

from __future__ import annotations

import asyncio
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
    FileReferenceExpiredError,
    MessageIdInvalidError,
)
from telethon.tl.custom.message import Message

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

CHUNK_SIZE = 1024 * 1024

ALLOWED_MEDIA_CATEGORIES = {
    "photo",
    "video",
    "document",
    "audio",
    "voice",
    "sticker",
    "animation",
    "other",
}


@dataclass(frozen=True, slots=True)
class TelegramMediaInfo:
    """Normalised metadata for a Telegram media attachment."""

    media_id: str
    message_id: int
    chat_id: int
    media_type: str
    file_name: str | None
    mime_type: str | None
    file_size: int | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    is_streaming: bool


@dataclass(frozen=True, slots=True)
class DownloadedTelegramMedia:
    """Result of a successful Telegram media download."""

    media: TelegramMediaInfo
    file_path: Path
    file_size: int


class TelegramMediaService:
    """Inspect and download Telegram message attachments."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
        storage_dir: Path,
        *,
        max_download_size: int = 2 * 1024 * 1024 * 1024,
    ) -> None:
        if max_download_size <= 0:
            raise ValueError("max_download_size must be positive.")

        self.client_manager = client_manager
        self.storage_dir = Path(storage_dir).expanduser().resolve()
        self.max_download_size = max_download_size
        self._download_lock = asyncio.Lock()

    async def get_media_info(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
    ) -> TelegramMediaInfo | None:
        """Retrieve metadata for a message's media attachment."""
        self._validate_identifiers(account_id, chat_id, message_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            message = await client.get_messages(
                chat_id,
                ids=message_id,
            )
        except (
            ChannelPrivateError,
            ChatIdInvalidError,
            MessageIdInvalidError,
        ):
            raise

        if message is None or isinstance(message, list):
            return None

        if message.media is None:
            return None

        return self._normalise_media(message, chat_id)

    async def download_media(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        message_id: int,
    ) -> DownloadedTelegramMedia:
        """
        Download a Telegram media attachment into managed storage.

        Files are saved under a generated filename. Telegram-provided
        filenames are never used as filesystem paths.
        """
        self._validate_identifiers(account_id, chat_id, message_id)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        message = await client.get_messages(
            chat_id,
            ids=message_id,
        )

        if message is None or isinstance(message, list):
            raise LookupError("Telegram message was not found.")

        if message.media is None:
            raise ValueError("Telegram message does not contain media.")

        media_info = self._normalise_media(message, chat_id)

        if (
            media_info.file_size is not None
            and media_info.file_size > self.max_download_size
        ):
            raise ValueError("Media exceeds the configured download limit.")

        self._prepare_storage_directory()

        extension = self._get_extension(media_info)
        filename = f"{uuid.uuid4().hex}{extension}"

        destination = (self.storage_dir / filename).resolve()

        if destination.parent != self.storage_dir:
            raise ValueError("Invalid media destination path.")

        temporary_path = destination.with_name(
            f".{destination.name}.part"
        )

        async with self._download_lock:
            try:
                downloaded_path = await client.download_media(
                    message,
                    file=str(temporary_path),
                    part_size_kb=CHUNK_SIZE // 1024,
                )

                if downloaded_path is None:
                    raise RuntimeError(
                        "Telegram did not return a downloaded media file."
                    )

                actual_path = Path(downloaded_path).resolve()

                if actual_path != temporary_path.resolve():
                    raise RuntimeError(
                        "Telegram returned an unexpected download path."
                    )

                if not actual_path.is_file():
                    raise RuntimeError(
                        "Downloaded media file does not exist."
                    )

                actual_size = actual_path.stat().st_size

                if actual_size > self.max_download_size:
                    raise ValueError(
                        "Downloaded media exceeds the configured limit."
                    )

                if actual_size == 0:
                    raise RuntimeError("Downloaded media file is empty.")

                actual_path.replace(destination)

            except Exception:
                temporary_path.unlink(missing_ok=True)

                logger.exception(
                    "telegram_media_download_failed",
                    account_id=account_id,
                    chat_id=chat_id,
                    message_id=message_id,
                )
                raise

        logger.info(
            "telegram_media_downloaded",
            account_id=account_id,
            chat_id=chat_id,
            message_id=message_id,
            file_size=actual_size,
        )

        return DownloadedTelegramMedia(
            media=media_info,
            file_path=destination,
            file_size=actual_size,
        )

    async def delete_downloaded_media(
        self,
        file_path: Path,
    ) -> bool:
        """
        Delete a previously downloaded media file.

        Only files directly inside the configured storage directory
        can be deleted through this method.
        """
        path = Path(file_path).expanduser().resolve()

        if path.parent != self.storage_dir:
            raise ValueError(
                "The requested file is outside the media storage directory."
            )

        if not path.is_file():
            return False

        path.unlink()

        logger.info(
            "telegram_downloaded_media_deleted",
            filename=path.name,
        )

        return True

    def _prepare_storage_directory(self) -> None:
        """Create the media storage directory with restrictive permissions."""
        self.storage_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o750,
        )

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

    @classmethod
    def _normalise_media(
        cls,
        message: Message,
        chat_id: int,
    ) -> TelegramMediaInfo:
        """Convert Telethon media metadata into an application representation."""
        media = message.media
        document = getattr(media, "document", None)
        photo = getattr(media, "photo", None)

        media_type = cls._get_media_type(message)

        file_name = None
        mime_type = None
        file_size = None
        duration = None
        width = None
        height = None
        is_streaming = False

        if document is not None:
            mime_type = getattr(document, "mime_type", None)
            file_size = getattr(document, "size", None)

            for attribute in getattr(document, "attributes", []):
                attribute_name = type(attribute).__name__

                if attribute_name == "DocumentAttributeFilename":
                    file_name = attribute.file_name

                elif attribute_name == "DocumentAttributeVideo":
                    duration = attribute.duration
                    width = attribute.w
                    height = attribute.h
                    is_streaming = bool(
                        getattr(attribute, "supports_streaming", False)
                    )

                elif attribute_name == "DocumentAttributeAudio":
                    duration = attribute.duration

        elif photo is not None:
            file_name = None
            mime_type = "image/jpeg"

        if file_name:
            file_name = Path(file_name).name

        return TelegramMediaInfo(
            media_id=(
                f"{chat_id}:{message.id}"
            ),
            message_id=message.id,
            chat_id=chat_id,
            media_type=media_type,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            duration_seconds=duration,
            width=width,
            height=height,
            is_streaming=is_streaming,
        )

    @staticmethod
    def _get_media_type(message: Message) -> str:
        """Identify the Telegram media category."""
        media = message.media

        if media is None:
            return "other"

        media_name = type(media).__name__

        if media_name == "MessageMediaPhoto":
            return "photo"

        if media_name == "MessageMediaDocument":
            document = getattr(media, "document", None)

            for attribute in getattr(document, "attributes", []):
                attribute_name = type(attribute).__name__

                if attribute_name == "DocumentAttributeVideo":
                    return "video"

                if attribute_name == "DocumentAttributeAudio":
                    return (
                        "voice"
                        if getattr(attribute, "voice", False)
                        else "audio"
                    )

                if attribute_name == "DocumentAttributeSticker":
                    return "sticker"

                if attribute_name == "DocumentAttributeAnimated":
                    return "animation"

            return "document"

        return "other"

    @staticmethod
    def _get_extension(media: TelegramMediaInfo) -> str:
        """Determine a safe file extension from MIME type or filename."""
        if media.file_name:
            suffix = Path(media.file_name).suffix.lower()

            if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                return suffix

        if media.mime_type:
            extension = mimetypes.guess_extension(media.mime_type)

            if extension:
                return extension

        return ".bin"

    @staticmethod
    def _validate_identifiers(
        account_id: int,
        chat_id: int,
        message_id: int,
    ) -> None:
        """Validate Telegram and internal account identifiers."""
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")

        if message_id <= 0:
            raise ValueError("message_id must be positive.")
