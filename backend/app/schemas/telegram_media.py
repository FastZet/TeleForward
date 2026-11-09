
"""
TeleForward Telegram media schemas.

Defines:
- Telegram media types.
- Media metadata and file references.
- Media download and processing states.
- Media processing results.

Security:
- Never expose local filesystem paths to unauthorised clients.
- Validate file size and MIME type independently of Telegram metadata.
- Treat filenames and media attributes as untrusted input.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class TelegramMediaTypeSchema(StrEnum):
    """Supported Telegram media categories."""

    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    ANIMATION = "animation"
    STICKER = "sticker"
    CONTACT = "contact"
    LOCATION = "location"
    POLL = "poll"
    UNKNOWN = "unknown"


class MediaProcessingStatusSchema(StrEnum):
    """Media processing lifecycle states."""

    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


class TelegramMediaMetadata(RequestSchema):
    """Metadata extracted from a Telegram media object."""

    media_type: TelegramMediaTypeSchema

    file_name: str | None = Field(
        default=None,
        max_length=255,
    )

    mime_type: str | None = Field(
        default=None,
        max_length=255,
    )

    file_size: int | None = Field(
        default=None,
        ge=0,
    )

    width: int | None = Field(
        default=None,
        gt=0,
    )

    height: int | None = Field(
        default=None,
        gt=0,
    )

    duration_seconds: float | None = Field(
        default=None,
        ge=0,
    )

    supports_streaming: bool = False

    has_thumbnail: bool = False

    @model_validator(mode="after")
    def validate_dimensions(self):
        """Require width and height together."""

        if (self.width is None) != (self.height is None):
            raise ValueError(
                "width and height must either both be supplied "
                "or both be omitted"
            )

        return self


class TelegramMediaFileReference(RequestSchema):
    """Internal reference to a downloaded media file."""

    media_id: int = Field(
        gt=0,
    )

    file_name: str = Field(
        min_length=1,
        max_length=255,
    )

    mime_type: str | None = Field(
        default=None,
        max_length=255,
    )

    file_size: int = Field(
        ge=0,
    )

    checksum_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-fA-F0-9]{64}$",
    )


class TelegramMediaDownloadRequest(RequestSchema):
    """Request media download for an existing Telegram message."""

    account_id: int = Field(
        gt=0,
    )

    chat_id: int

    message_id: int = Field(
        gt=0,
    )

    maximum_size_bytes: int | None = Field(
        default=None,
        gt=0,
    )

    generate_thumbnail: bool = False


class TelegramMediaProcessingRequest(RequestSchema):
    """Request processing of an existing media attachment."""

    media_id: int = Field(
        gt=0,
    )

    generate_thumbnail: bool = False

    extract_metadata: bool = True

    verify_checksum: bool = True


class TelegramMediaResponse(ResponseSchema):
    """Media attachment information safe for API responses."""

    id: int

    message_id: int

    media_type: TelegramMediaTypeSchema

    file_name: str | None = None

    mime_type: str | None = None

    file_size: int | None = None

    width: int | None = None
    height: int | None = None

    duration_seconds: float | None = None

    supports_streaming: bool = False

    status: MediaProcessingStatusSchema

    checksum_sha256: str | None = None

    created_at: datetime
    updated_at: datetime


class TelegramMediaProcessingResult(ResponseSchema):
    """Result of media download or processing."""

    media_id: int

    status: MediaProcessingStatusSchema

    file_size: int | None = None

    checksum_sha256: str | None = None

    thumbnail_available: bool = False

    error_message: str | None = None

    processed_at: datetime | None = None
