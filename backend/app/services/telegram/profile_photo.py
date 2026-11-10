"""
Telegram profile-photo service.

Supports:
- Retrieving profile-photo metadata.
- Downloading the current profile photo.
- Uploading a new profile photo.
- Deleting profile photos.
- Validating local image files.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog
from telethon import TelegramClient, functions, types
from telethon.errors import (
    FloodWaitError,
    PhotoInvalidError,
    PhotoSaveFileInvalidError,
)

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)

MAX_PROFILE_PHOTO_SIZE = 10 * 1024 * 1024

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
}


@dataclass(frozen=True, slots=True)
class TelegramProfilePhoto:
    """Telegram profile-photo metadata."""

    photo_id: int
    date: int | None
    has_video: bool
    is_personal: bool
    file_size: int | None


@dataclass(frozen=True, slots=True)
class TelegramProfilePhotoResult:
    """Result of a profile-photo operation."""

    account_id: int
    photo_id: int | None
    successful: bool
    file_path: str | None = None


class TelegramProfilePhotoService:
    """Manage Telegram account profile photos."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
        storage_dir: str | Path,
    ) -> None:
        self.client_manager = client_manager
        self.storage_dir = Path(storage_dir).expanduser().resolve()

        self.storage_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

    async def get_profile_photos(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        limit: int = 10,
    ) -> tuple[TelegramProfilePhoto, ...]:
        """Retrieve profile-photo metadata."""
        if not 1 <= limit <= 100:
            raise ValueError(
                "limit must be between 1 and 100."
            )

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            photos = await client.get_profile_photos(
                "me",
                limit=limit,
            )

        except FloodWaitError:
            logger.warning(
                "telegram_profile_photos_retrieval_flood_wait",
                account_id=account_id,
            )
            raise

        results: list[TelegramProfilePhoto] = []

        for photo in photos:
            if not isinstance(photo, types.Photo):
                continue

            results.append(
                TelegramProfilePhoto(
                    photo_id=photo.id,
                    date=(
                        int(photo.date.timestamp())
                        if photo.date is not None
                        else None
                    ),
                    has_video=bool(
                        getattr(photo, "has_video", False)
                    ),
                    is_personal=bool(
                        getattr(photo, "personal", False)
                    ),
                    file_size=None,
                )
            )

        return tuple(results)

    async def download_profile_photo(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        photo_id: int | None = None,
    ) -> TelegramProfilePhotoResult:
        """Download the current or a specific profile photo."""
        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        account_dir = self._get_account_directory(account_id)

        destination = account_dir / (
            f"{uuid.uuid4().hex}.jpg"
        )

        try:
            if photo_id is None:
                downloaded = await client.download_profile_photo(
                    "me",
                    file=str(destination),
                )
            else:
                photos = await client.get_profile_photos(
                    "me",
                    limit=100,
                )

                selected_photo = next(
                    (
                        photo
                        for photo in photos
                        if getattr(photo, "id", None) == photo_id
                    ),
                    None,
                )

                if selected_photo is None:
                    raise ValueError(
                        "The requested profile photo was not found."
                    )

                downloaded = await client.download_media(
                    selected_photo,
                    file=str(destination),
                )

        except FloodWaitError:
            logger.warning(
                "telegram_profile_photo_download_flood_wait",
                account_id=account_id,
            )
            raise

        if not downloaded or not destination.is_file():
            return TelegramProfilePhotoResult(
                account_id=account_id,
                photo_id=photo_id,
                successful=False,
            )

        logger.info(
            "telegram_profile_photo_downloaded",
            account_id=account_id,
            photo_id=photo_id,
        )

        return TelegramProfilePhotoResult(
            account_id=account_id,
            photo_id=photo_id,
            successful=True,
            file_path=str(destination),
        )

    async def upload_profile_photo(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        file_path: str | Path,
    ) -> TelegramProfilePhotoResult:
        """Upload a replacement profile photo."""
        validated_path = self._validate_image(file_path)

        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            uploaded = await client.upload_file(
                str(validated_path)
            )

            photo = await client(
                functions.photos.UploadProfilePhotoRequest(
                    file=uploaded,
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_profile_photo_upload_flood_wait",
                account_id=account_id,
            )
            raise

        except (
            PhotoInvalidError,
            PhotoSaveFileInvalidError,
        ):
            logger.exception(
                "telegram_profile_photo_upload_failed",
                account_id=account_id,
            )
            raise

        photo_id = getattr(
            getattr(photo, "photo", None),
            "id",
            None,
        )

        logger.info(
            "telegram_profile_photo_uploaded",
            account_id=account_id,
            photo_id=photo_id,
        )

        return TelegramProfilePhotoResult(
            account_id=account_id,
            photo_id=photo_id,
            successful=True,
        )

    async def delete_profile_photo(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
        *,
        photo_id: int | None = None,
    ) -> TelegramProfilePhotoResult:
        """Delete a profile photo."""
        client = await self._get_authorized_client(
            account_id,
            api_id,
            api_hash,
        )

        try:
            photos = await client.get_profile_photos(
                "me",
                limit=100,
            )

            selected_photo = next(
                (
                    photo
                    for photo in photos
                    if isinstance(photo, types.Photo)
                    and (
                        photo_id is None
                        or photo.id == photo_id
                    )
                ),
                None,
            )

            if selected_photo is None:
                raise ValueError(
                    "The requested profile photo was not found."
                )

            await client(
                functions.photos.DeletePhotosRequest(
                    id=[
                        types.InputPhoto(
                            id=selected_photo.id,
                            access_hash=selected_photo.access_hash,
                            file_reference=selected_photo.file_reference,
                        )
                    ]
                )
            )

        except FloodWaitError:
            logger.warning(
                "telegram_profile_photo_delete_flood_wait",
                account_id=account_id,
            )
            raise

        logger.info(
            "telegram_profile_photo_deleted",
            account_id=account_id,
            photo_id=selected_photo.id,
        )

        return TelegramProfilePhotoResult(
            account_id=account_id,
            photo_id=selected_photo.id,
            successful=True,
        )

    def _validate_image(
        self,
        file_path: str | Path,
    ) -> Path:
        """Validate a profile-photo image inside managed storage."""
        path = Path(file_path)

        if path.is_symlink():
            raise ValueError(
                "Symbolic-link uploads are not permitted."
            )

        resolved = path.resolve(strict=True)

        if not resolved.is_relative_to(self.storage_dir):
            raise ValueError(
                "Image must be inside managed storage."
            )

        if not resolved.is_file():
            raise ValueError(
                "Image path must reference a regular file."
            )

        if resolved.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError(
                "Only JPEG and PNG images are supported."
            )

        if resolved.stat().st_size > MAX_PROFILE_PHOTO_SIZE:
            raise ValueError(
                "Profile photo exceeds the maximum allowed size."
            )

        if resolved.stat().st_size == 0:
            raise ValueError(
                "Profile photo cannot be empty."
            )

        return resolved

    def _get_account_directory(
        self,
        account_id: int,
    ) -> Path:
        """Get the account-specific photo directory."""
        if account_id <= 0:
            raise ValueError(
                "account_id must be positive."
            )

        account_dir = self.storage_dir / str(account_id)

        account_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        resolved = account_dir.resolve(strict=True)

        if not resolved.is_relative_to(self.storage_dir):
            raise ValueError(
                "Invalid profile-photo storage directory."
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
