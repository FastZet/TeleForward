"""
TeleForward media filtering utilities.

Provides media classification and matching operations for Telegram messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class MediaType(StrEnum):
    """Supported Telegram media categories."""

    NONE = "none"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    STICKER = "sticker"
    ANIMATION = "animation"
    CONTACT = "contact"
    LOCATION = "location"
    POLL = "poll"
    GAME = "game"
    WEB_PAGE = "web_page"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    """Normalised media information."""

    media_type: MediaType
    mime_type: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    is_animated: bool = False
    is_streaming: bool = False
    attributes: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class MediaFilterResult:
    """Result of media filter evaluation."""

    matched: bool
    detected_type: MediaType
    reason: str


class MediaFilter:
    """Classify Telegram media and evaluate media filters."""

    _MIME_TYPE_MAP: dict[str, MediaType] = {
        "image/jpeg": MediaType.PHOTO,
        "image/png": MediaType.PHOTO,
        "image/webp": MediaType.PHOTO,
        "image/gif": MediaType.ANIMATION,
        "video/mp4": MediaType.VIDEO,
        "video/webm": MediaType.VIDEO,
        "audio/mpeg": MediaType.AUDIO,
        "audio/mp3": MediaType.AUDIO,
        "audio/ogg": MediaType.VOICE,
        "audio/opus": MediaType.VOICE,
        "audio/aac": MediaType.AUDIO,
        "audio/flac": MediaType.AUDIO,
        "application/pdf": MediaType.DOCUMENT,
    }

    _EXTENSION_MAP: dict[str, MediaType] = {
        ".jpg": MediaType.PHOTO,
        ".jpeg": MediaType.PHOTO,
        ".png": MediaType.PHOTO,
        ".webp": MediaType.PHOTO,
        ".gif": MediaType.ANIMATION,
        ".mp4": MediaType.VIDEO,
        ".mkv": MediaType.VIDEO,
        ".mov": MediaType.VIDEO,
        ".webm": MediaType.VIDEO,
        ".mp3": MediaType.AUDIO,
        ".m4a": MediaType.AUDIO,
        ".aac": MediaType.AUDIO,
        ".flac": MediaType.AUDIO,
        ".ogg": MediaType.AUDIO,
        ".opus": MediaType.VOICE,
        ".pdf": MediaType.DOCUMENT,
        ".zip": MediaType.DOCUMENT,
        ".rar": MediaType.DOCUMENT,
        ".7z": MediaType.DOCUMENT,
        ".doc": MediaType.DOCUMENT,
        ".docx": MediaType.DOCUMENT,
        ".xls": MediaType.DOCUMENT,
        ".xlsx": MediaType.DOCUMENT,
        ".ppt": MediaType.DOCUMENT,
        ".pptx": MediaType.DOCUMENT,
        ".txt": MediaType.DOCUMENT,
    }

    def classify(self, media: Any) -> MediaMetadata:
        """Classify a Telethon media object or normalised mapping."""
        if media is None:
            return MediaMetadata(media_type=MediaType.NONE)

        if isinstance(media, Mapping):
            return self._classify_mapping(media)

        class_name = type(media).__name__.lower()

        if class_name == "message":
            media = getattr(media, "media", None)

            if media is None:
                return MediaMetadata(media_type=MediaType.NONE)

            class_name = type(media).__name__.lower()

        if "photo" in class_name:
            return MediaMetadata(
                media_type=MediaType.PHOTO
            )

        if "document" in class_name:
            return self._classify_document(media)

        if "webpage" in class_name or "web_page" in class_name:
            return MediaMetadata(
                media_type=MediaType.WEB_PAGE
            )

        if "geo" in class_name or "venue" in class_name:
            return MediaMetadata(
                media_type=MediaType.LOCATION
            )

        if "contact" in class_name:
            return MediaMetadata(
                media_type=MediaType.CONTACT
            )

        if "poll" in class_name:
            return MediaMetadata(
                media_type=MediaType.POLL
            )

        if "game" in class_name:
            return MediaMetadata(
                media_type=MediaType.GAME
            )

        return MediaMetadata(
            media_type=MediaType.UNKNOWN
        )

    def _classify_mapping(
        self,
        media: Mapping[str, Any],
    ) -> MediaMetadata:
        """Classify media represented as a dictionary."""
        raw_type = media.get("media_type") or media.get("type")

        try:
            media_type = MediaType(raw_type)
        except (ValueError, TypeError):
            media_type = self._infer_from_metadata(media)

        return MediaMetadata(
            media_type=media_type,
            mime_type=media.get("mime_type"),
            file_name=media.get("file_name"),
            file_size=self._optional_int(media.get("file_size")),
            duration=self._optional_float(media.get("duration")),
            width=self._optional_int(media.get("width")),
            height=self._optional_int(media.get("height")),
            is_animated=bool(media.get("is_animated", False)),
            is_streaming=bool(media.get("is_streaming", False)),
            attributes=media.get("attributes"),
        )

    def _classify_document(
        self,
        document: Any,
    ) -> MediaMetadata:
        """Classify Telegram document media using its attributes."""
        mime_type = getattr(document, "mime_type", None)

        attributes = getattr(document, "attributes", ()) or ()

        file_name = None
        duration = None
        width = None
        height = None
        is_animated = False

        for attribute in attributes:
            attribute_name = type(attribute).__name__.lower()

            if "filename" in attribute_name:
                file_name = getattr(attribute, "file_name", None)

            elif "video" in attribute_name:
                duration = getattr(attribute, "duration", None)
                width = getattr(attribute, "w", None)
                height = getattr(attribute, "h", None)

            elif "audio" in attribute_name:
                duration = getattr(attribute, "duration", None)

                if getattr(attribute, "voice", False):
                    media_type = MediaType.VOICE
                else:
                    media_type = MediaType.AUDIO

                return MediaMetadata(
                    media_type=media_type,
                    mime_type=mime_type,
                    file_name=file_name,
                    file_size=getattr(document, "size", None),
                    duration=duration,
                )

            elif "animated" in attribute_name:
                is_animated = True

            elif "sticker" in attribute_name:
                return MediaMetadata(
                    media_type=MediaType.STICKER,
                    mime_type=mime_type,
                    file_name=file_name,
                    file_size=getattr(document, "size", None),
                )

        if is_animated:
            media_type = MediaType.ANIMATION
        elif mime_type and mime_type.startswith("video/"):
            media_type = MediaType.VIDEO
        elif mime_type and mime_type.startswith("image/"):
            media_type = MediaType.PHOTO
        else:
            media_type = self._MIME_TYPE_MAP.get(
                mime_type,
                MediaType.DOCUMENT,
            )

        return MediaMetadata(
            media_type=media_type,
            mime_type=mime_type,
            file_name=file_name,
            file_size=getattr(document, "size", None),
            duration=duration,
            width=width,
            height=height,
            is_animated=is_animated,
        )

    def _infer_from_metadata(
        self,
        media: Mapping[str, Any],
    ) -> MediaType:
        """Infer a media category from MIME type or file extension."""
        mime_type = media.get("mime_type")

        if isinstance(mime_type, str):
            normalised_mime = mime_type.lower().split(";")[0].strip()

            media_type = self._MIME_TYPE_MAP.get(normalised_mime)

            if media_type is not None:
                return media_type

            if normalised_mime.startswith("video/"):
                return MediaType.VIDEO

            if normalised_mime.startswith("image/"):
                return MediaType.PHOTO

            if normalised_mime.startswith("audio/"):
                return MediaType.AUDIO

        file_name = media.get("file_name")

        if isinstance(file_name, str):
            from pathlib import PurePath

            extension = PurePath(file_name).suffix.lower()

            return self._EXTENSION_MAP.get(
                extension,
                MediaType.UNKNOWN,
            )

        return MediaType.UNKNOWN

    def matches(
        self,
        media: Any,
        allowed_types: set[MediaType] | frozenset[MediaType],
        *,
        include_no_media: bool = False,
    ) -> MediaFilterResult:
        """Check whether detected media belongs to an allowed set."""
        metadata = self.classify(media)

        if metadata.media_type == MediaType.NONE:
            matched = include_no_media
        else:
            matched = metadata.media_type in allowed_types

        return MediaFilterResult(
            matched=matched,
            detected_type=metadata.media_type,
            reason=(
                "Media type is allowed."
                if matched
                else "Media type is not allowed."
            ),
        )

    def matches_any(
        self,
        media: Any,
        blocked_types: set[MediaType] | frozenset[MediaType],
    ) -> MediaFilterResult:
        """Check whether detected media is not in a blocked set."""
        metadata = self.classify(media)

        matched = metadata.media_type not in blocked_types

        return MediaFilterResult(
            matched=matched,
            detected_type=metadata.media_type,
            reason=(
                "Media type is not blocked."
                if matched
                else "Media type is blocked."
            ),
        )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None

        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None

        try:
            return float(value)
        except (ValueError, TypeError):
            return None
