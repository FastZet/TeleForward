"""
Telegram media-upload service.

Supports:
- Uploading individual files.
- Uploading multiple files.
- Optional captions and formatting entities.
- Document and streaming-video upload modes.
- File-size and storage-path validation.
- Normalised upload results.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import structlog
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatIdInvalidError,
    FloodWaitError,
    PeerIdInvalidError,
)
from telethon.tl.custom.message import Message

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

DEFAULT_MAX_UPLOAD_SIZE = 512 * 1024 * 1024
MAX_UPLOAD_BATCH_SIZE = 10


@dataclass(frozen=True, slots=True)
class TelegramUploadResult:
    """Result of uploading a file to Telegram."""

    account_id: int
    chat_id: int
    message_id: int
    file_name: str
    file_size: int
    mime_type: str | None
    successful: bool


@dataclass(frozen=True, slots=True)
class TelegramBatchUploadResult:
    """Result of uploading multiple files."""

    account_id: int
    chat_id: int
    results: tuple[TelegramUploadResult, ...]
    successful_count: int
    failed_files: tuple[str, ...]


class TelegramUploadService:
    """Upload local files to Telegram chats."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
        storage_dir: str | Path,
        max_upload_size: int = DEFAULT_MAX_UPLOAD_SIZE,
    ) -> None:
        self.client_manager = client_manager
        self.storage_dir = Path(storage_dir).expanduser().resolve()
        self.max_upload_size = max_upload_size

        if max_upload_size <= 0:
            raise ValueError(
                "max_upload_size must be positive."
            )

        self.storage_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        if self.storage_dir.is_symlink():
            raise ValueError(
                "Upload storage directory cannot be a symbolic link."
            )

    async def upload_file(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        file_path: str | Path,
        *,
        caption: str | None = None,
        silent: bool = False,
        force_document: bool = False,
        supports_streaming: bool = False,
        formatting_entities: Sequence[object] | None = None,
        reply_to: int | None = None,
    ) -> TelegramUploadResult:
        """Upload one file to a Telegram chat."""
        self._validate_identifiers(account_id, chat_id)

        if caption is not None and len(caption) > 4096:
            raise ValueError(
                "Caption cannot exceed 4096 characters."
            )

        if reply_to is not None and reply_to <= 0:
            raise ValueError("reply_to must be positive.")

        validated_path = self._validate_file(file_path)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        destination = await client.get_input_entity(chat_id)

        try:
            uploaded = await client.send_file(
                destination,
                file=str(validated_path),
                caption=caption,
                formatting_entities=(
                    list(formatting_entities)
                    if formatting_entities is not None
                    else None
                ),
                silent=silent,
                force_document=force_document,
                supports_streaming=supports_streaming,
                reply_to=reply_to,
                parse_mode=None,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_file_upload_flood_wait",
                account_id=account_id,
                chat_id=chat_id,
                file_name=validated_path.name,
            )
            raise

        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
            PeerIdInvalidError,
        ):
            logger.exception(
                "telegram_file_upload_failed",
                account_id=account_id,
                chat_id=chat_id,
                file_name=validated_path.name,
            )
            raise

        messages = (
            uploaded
            if isinstance(uploaded, list)
            else [uploaded]
        )

        valid_messages = [
            message
            for message in messages
            if isinstance(message, Message)
        ]

        if not valid_messages:
            raise RuntimeError(
                "Telegram did not return an uploaded message."
            )

        message = valid_messages[0]

        result = TelegramUploadResult(
            account_id=account_id,
            chat_id=chat_id,
            message_id=message.id,
            file_name=validated_path.name,
            file_size=validated_path.stat().st_size,
            mime_type=(
                getattr(message.file, "mime_type", None)
                if message.file is not None
                else None
            ),
            successful=True,
        )

        logger.info(
            "telegram_file_uploaded",
            account_id=account_id,
            chat_id=chat_id,
            message_id=message.id,
            file_name=validated_path.name,
            file_size=result.file_size,
        )

        return result

    async def upload_files(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        chat_id: int,
        file_paths: Sequence[str | Path],
        *,
        captions: Sequence[str | None] | None = None,
        silent: bool = False,
        force_document: bool = False,
        supports_streaming: bool = False,
    ) -> TelegramBatchUploadResult:
        """
        Upload multiple files as one Telegram media group.

        Telegram supports a maximum of 10 media items per album.
        All files must pass validation before upload begins.
        """
        self._validate_identifiers(account_id, chat_id)

        if not file_paths:
            raise ValueError("At least one file is required.")

        if len(file_paths) > MAX_UPLOAD_BATCH_SIZE:
            raise ValueError(
                f"A maximum of {MAX_UPLOAD_BATCH_SIZE} files "
                "can be uploaded together."
            )

        if captions is not None:
            if len(captions) != len(file_paths):
                raise ValueError(
                    "The number of captions must match the number of files."
                )

            if any(
                caption is not None and len(caption) > 4096
                for caption in captions
            ):
                raise ValueError(
                    "A caption cannot exceed 4096 characters."
                )

        validated_paths = [
            self._validate_file(path)
            for path in file_paths
        ]

        total_size = sum(
            path.stat().st_size
            for path in validated_paths
        )

        if total_size > self.max_upload_size:
            raise ValueError(
                "Combined upload size exceeds the configured limit."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        destination = await client.get_input_entity(chat_id)

        effective_captions = (
            list(captions)
            if captions is not None
            else [None] * len(validated_paths)
        )

        try:
            uploaded = await client.send_file(
                destination,
                file=[str(path) for path in validated_paths],
                caption=effective_captions,
                silent=silent,
                force_document=force_document,
                supports_streaming=supports_streaming,
                parse_mode=None,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_batch_upload_flood_wait",
                account_id=account_id,
                chat_id=chat_id,
                file_count=len(validated_paths),
            )
            raise

        except (
            ChannelPrivateError,
            ChatAdminRequiredError,
            ChatIdInvalidError,
            PeerIdInvalidError,
        ):
            logger.exception(
                "telegram_batch_upload_failed",
                account_id=account_id,
                chat_id=chat_id,
                file_count=len(validated_paths),
            )
            raise

        messages = (
            uploaded
            if isinstance(uploaded, list)
            else [uploaded]
        )

        valid_messages = [
            message
            for message in messages
            if isinstance(message, Message)
        ]

        results: list[TelegramUploadResult] = []

        for index, message in enumerate(valid_messages):
            if index >= len(validated_paths):
                break

            path = validated_paths[index]

            results.append(
                TelegramUploadResult(
                    account_id=account_id,
                    chat_id=chat_id,
                    message_id=message.id,
                    file_name=path.name,
                    file_size=path.stat().st_size,
                    mime_type=(
                        getattr(message.file, "mime_type", None)
                        if message.file is not None
                        else None
                    ),
                    successful=True,
                )
            )

        successful_count = len(results)

        failed_files = tuple(
            path.name
            for path in validated_paths[successful_count:]
        )

        logger.info(
            "telegram_batch_upload_completed",
            account_id=account_id,
            chat_id=chat_id,
            uploaded_count=successful_count,
            failed_count=len(failed_files),
        )

        return TelegramBatchUploadResult(
            account_id=account_id,
            chat_id=chat_id,
            results=tuple(results),
            successful_count=successful_count,
            failed_files=failed_files,
        )

    def _validate_file(
        self,
        file_path: str | Path,
    ) -> Path:
        """Validate that a file belongs to managed upload storage."""
        path = Path(file_path)

        if path.is_symlink():
            raise ValueError(
                "Symbolic-link uploads are not permitted."
            )

        resolved = path.resolve(strict=True)

        if not resolved.is_relative_to(self.storage_dir):
            raise ValueError(
                "Upload file must be inside managed storage."
            )

        if not resolved.is_file():
            raise ValueError(
                "Upload path must reference a regular file."
            )

        size = resolved.stat().st_size

        if size <= 0:
            raise ValueError("Empty files cannot be uploaded.")

        if size > self.max_upload_size:
            raise ValueError(
                "File exceeds the configured upload-size limit."
            )

        return resolved

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
        chat_id: int,
    ) -> None:
        if account_id <= 0:
            raise ValueError("account_id must be positive.")

        if chat_id == 0:
            raise ValueError("chat_id cannot be zero.")
