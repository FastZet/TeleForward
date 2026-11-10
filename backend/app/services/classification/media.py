"""
TeleForward media classifier.

Classifies Telegram messages according to their media type and
available media metadata.
"""

from __future__ import annotations

import logging
import time

from collections.abc import Mapping
from typing import Any

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)


logger = logging.getLogger(__name__)

MAX_METADATA_VALUE_LENGTH = 512

MEDIA_ALIASES: dict[str, str] = {
    "photo": "photo",
    "image": "photo",
    "messagemediaphoto": "photo",

    "video": "video",
    "messagemediavideo": "video",

    "audio": "audio",
    "music": "audio",
    "messageaudio": "audio",

    "voice": "voice",
    "voice_message": "voice",
    "voicemessage": "voice",

    "video_note": "video_note",
    "videonote": "video_note",

    "document": "document",
    "file": "document",
    "messagemediadocument": "document",

    "sticker": "sticker",
    "messagemediasticker": "sticker",

    "animation": "animation",
    "gif": "animation",

    "contact": "contact",
    "messagemediacontact": "contact",

    "location": "location",
    "geo": "location",
    "messagemediageo": "location",

    "venue": "venue",
    "messagemediavenue": "venue",

    "poll": "poll",
    "messagemediapoll": "poll",

    "game": "game",
    "messagemediagame": "game",

    "webpage": "webpage",
    "messagemediawebpage": "webpage",
}

MIME_PREFIX_ALIASES: dict[str, str] = {
    "image/": "photo",
    "video/": "video",
    "audio/": "audio",
}

SUPPORTED_CATEGORIES = frozenset(
    {
        "photo",
        "video",
        "audio",
        "voice",
        "video_note",
        "document",
        "sticker",
        "animation",
        "contact",
        "location",
        "venue",
        "poll",
        "game",
        "webpage",
    }
)


class MediaClassifier(BaseClassifier):
    """Classify messages based on Telegram media information."""

    name = "media"
    version = "1.0.0"

    def __init__(
        self,
        *,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
        classify_documents_by_mime: bool = True,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        if not isinstance(classify_documents_by_mime, bool):
            raise ValueError(
                "classify_documents_by_mime must be a boolean."
            )

        self.classify_documents_by_mime = (
            classify_documents_by_mime
        )

    @staticmethod
    def _normalise_value(value: Any) -> str | None:
        """Convert a metadata value into a normalised string."""
        if not isinstance(value, str):
            return None

        normalised = value.strip().lower()

        if not normalised:
            return None

        return normalised[:MAX_METADATA_VALUE_LENGTH]

    @staticmethod
    def _get_metadata_value(
        metadata: Mapping[str, Any],
        *keys: str,
    ) -> str | None:
        """Retrieve the first usable string metadata value."""
        for key in keys:
            value = MediaClassifier._normalise_value(
                metadata.get(key)
            )

            if value:
                return value

        return None

    def _resolve_media_category(
        self,
        classification_input: ClassificationInput,
    ) -> tuple[str | None, str]:
        """Determine the most specific available media category."""
        metadata = classification_input.metadata

        media_type = self._normalise_value(
            classification_input.media_type
        )

        if media_type:
            category = MEDIA_ALIASES.get(media_type)

            if category:
                return category, "media_type"

        # Explicit metadata can distinguish media types that share
        # the same Telegram document representation.
        if metadata.get("is_voice") is True:
            return "voice", "metadata.is_voice"

        if metadata.get("is_video_note") is True:
            return "video_note", "metadata.is_video_note"

        if metadata.get("is_sticker") is True:
            return "sticker", "metadata.is_sticker"

        if metadata.get("is_animation") is True:
            return "animation", "metadata.is_animation"

        mime_type = self._get_metadata_value(
            metadata,
            "mime_type",
            "mime",
        )

        if mime_type:
            if self.classify_documents_by_mime:
                for prefix, category in MIME_PREFIX_ALIASES.items():
                    if mime_type.startswith(prefix):
                        return category, "metadata.mime_type"

            return "document", "metadata.mime_type"

        file_name = self._get_metadata_value(
            metadata,
            "file_name",
            "filename",
        )

        if file_name:
            extension = file_name.rpartition(".")[2]

            if extension:
                extension = extension.lower()

                if extension in {
                    "jpg", "jpeg", "png", "gif", "webp",
                    "bmp", "tif", "tiff", "heic",
                }:
                    return "photo", "metadata.file_name"

                if extension in {
                    "mp4", "mov", "avi", "mkv", "webm",
                    "m4v", "mpeg", "mpg",
                }:
                    return "video", "metadata.file_name"

                if extension in {
                    "mp3", "m4a", "aac", "ogg", "opus",
                    "wav", "flac", "wma",
                }:
                    return "audio", "metadata.file_name"

        return None, "unresolved"

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Classify a message according to its media type."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Media classifier is disabled.",
            )

        try:
            category, detection_source = (
                self._resolve_media_category(
                    classification_input
                )
            )

            if category is None:
                return self.skipped_result(
                    classifier=self.name,
                    reason="No supported media type could be identified.",
                )

            if category not in SUPPORTED_CATEGORIES:
                return self.skipped_result(
                    classifier=self.name,
                    reason=f"Unsupported media category: {category}.",
                )

            label = ClassificationLabel(
                name=category,
                category="media_type",
                confidence=1.0,
            )

            labels = self.filter_by_confidence((label,))

            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            return ClassificationResult(
                classifier=self.name,
                status=ClassificationStatus.COMPLETED,
                labels=labels,
                primary_label=labels[0] if labels else None,
                confidence=(
                    labels[0].confidence
                    if labels
                    else 0.0
                ),
                processing_time_ms=elapsed_ms,
                metadata={
                    "detected_media_type": category,
                    "detection_source": detection_source,
                    "mime_type": self._get_metadata_value(
                        classification_input.metadata,
                        "mime_type",
                        "mime",
                    ),
                    "file_name": self._get_metadata_value(
                        classification_input.metadata,
                        "file_name",
                        "filename",
                    ),
                },
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Media classification failed",
                extra={
                    "message_id": classification_input.message_id,
                    "classifier": self.name,
                },
            )

            return ClassificationResult(
                classifier=self.name,
                status=ClassificationStatus.FAILED,
                labels=(),
                primary_label=None,
                confidence=0.0,
                processing_time_ms=elapsed_ms,
                error=str(exc)[:2000],
                metadata={
                    "error_type": type(exc).__name__,
                },
            )
