"""
TeleForward message metadata classifier.

Extracts structured metadata from ClassificationInput objects.

The classifier relies only on metadata explicitly supplied by the
Telegram integration layer. It does not perform Telegram API calls.
"""

from __future__ import annotations

import logging
import time

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)


logger = logging.getLogger(__name__)

MAX_METADATA_FIELDS = 200
MAX_METADATA_DEPTH = 5
MAX_METADATA_STRING_LENGTH = 4_096
MAX_METADATA_ITEMS = 1_000

SUPPORTED_MEDIA_TYPES = frozenset({
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
    "poll",
    "web_page",
    "unknown",
})

SENSITIVE_FIELD_NAMES = frozenset({
    "password",
    "api_hash",
    "api_id",
    "access_token",
    "refresh_token",
    "secret",
    "session",
    "session_string",
    "phone_code",
    "phone_code_hash",
    "bot_token",
    "authorization",
    "cookie",
})


class MetadataClassifier(BaseClassifier):
    """Classify and extract Telegram message metadata."""

    name = "metadata"
    version = "1.0.0"

    def __init__(
        self,
        *,
        include_custom_metadata: bool = True,
        include_sender_metadata: bool = True,
        include_forward_metadata: bool = True,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        for name, value in (
            ("include_custom_metadata", include_custom_metadata),
            ("include_sender_metadata", include_sender_metadata),
            ("include_forward_metadata", include_forward_metadata),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean.")

        self.include_custom_metadata = include_custom_metadata
        self.include_sender_metadata = include_sender_metadata
        self.include_forward_metadata = include_forward_metadata

    @staticmethod
    def _sanitise_value(
        value: Any,
        *,
        depth: int = 0,
        key: str | None = None,
    ) -> Any:
        """
        Convert metadata into safe, JSON-compatible values.

        Sensitive fields are omitted recursively. Arbitrary Python
        objects are represented by their type name rather than repr().
        """
        if depth > MAX_METADATA_DEPTH:
            return "[maximum depth exceeded]"

        if key and key.casefold() in SENSITIVE_FIELD_NAMES:
            return "[redacted]"

        if value is None or isinstance(value, (bool, int, float)):
            return value

        if isinstance(value, str):
            return value[:MAX_METADATA_STRING_LENGTH]

        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.isoformat()

            return value.astimezone(timezone.utc).isoformat()

        if isinstance(value, Mapping):
            result: dict[str, Any] = {}

            for index, (child_key, child_value) in enumerate(
                value.items()
            ):
                if index >= MAX_METADATA_FIELDS:
                    result["_truncated"] = True
                    break

                if not isinstance(child_key, str):
                    continue

                if child_key.casefold() in SENSITIVE_FIELD_NAMES:
                    continue

                result[child_key[:128]] = MetadataClassifier._sanitise_value(
                    child_value,
                    depth=depth + 1,
                    key=child_key,
                )

            return result

        if isinstance(value, (list, tuple, set, frozenset)):
            result = []

            for item in list(value)[:MAX_METADATA_ITEMS]:
                result.append(
                    MetadataClassifier._sanitise_value(
                        item,
                        depth=depth + 1,
                    )
                )

            return result

        return {
            "unsupported_type": type(value).__name__,
        }

    @staticmethod
    def _normalise_timestamp(
        value: Any,
    ) -> str | None:
        """Return a timestamp in UTC ISO 8601 format."""
        if value is None:
            return None

        if not isinstance(value, datetime):
            return None

        if value.tzinfo is None:
            return None

        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _validate_media_type(
        media_type: str | None,
    ) -> str | None:
        """Normalise a media type."""
        if media_type is None:
            return None

        if not isinstance(media_type, str):
            return None

        normalised = media_type.strip().lower()

        if not normalised:
            return None

        if normalised in SUPPORTED_MEDIA_TYPES:
            return normalised

        return "unknown"

    def _build_metadata(
        self,
        classification_input: ClassificationInput,
    ) -> dict[str, Any]:
        """Construct a structured metadata representation."""
        metadata = classification_input.metadata

        result: dict[str, Any] = {
            "message_id": classification_input.message_id,
            "account_id": classification_input.account_id,
            "chat_id": classification_input.chat_id,
            "media_type": self._validate_media_type(
                classification_input.media_type
            ),
            "has_text": bool(classification_input.text),
            "has_caption": bool(classification_input.caption),
            "text_length": len(classification_input.text),
            "caption_length": len(classification_input.caption),
        }

        if self.include_sender_metadata:
            result["sender_id"] = classification_input.sender_id

        if self.include_custom_metadata:
            result["custom"] = self._sanitise_value(metadata)

        if self.include_forward_metadata:
            forward_fields = {
                "forwarded_from",
                "forwarded_from_id",
                "forwarded_from_name",
                "forward_date",
                "forwarded",
            }

            result["forwarding"] = {
                key: self._sanitise_value(value, key=key)
                for key, value in metadata.items()
                if key in forward_fields
            }

        timestamp = self._normalise_timestamp(
            metadata.get("date")
        )

        if timestamp is not None:
            result["timestamp"] = timestamp

        return result

    @staticmethod
    def _build_labels(
        metadata: Mapping[str, Any],
    ) -> tuple[ClassificationLabel, ...]:
        """Generate categorical labels from message metadata."""
        labels: list[ClassificationLabel] = []

        media_type = metadata.get("media_type")

        if media_type:
            labels.append(
                ClassificationLabel(
                    name=str(media_type),
                    category="media_type",
                    confidence=1.0,
                )
            )

        if metadata.get("has_text"):
            labels.append(
                ClassificationLabel(
                    name="text",
                    category="content_type",
                    confidence=1.0,
                )
            )

        if metadata.get("has_caption"):
            labels.append(
                ClassificationLabel(
                    name="caption",
                    category="content_type",
                    confidence=1.0,
                )
            )

        forwarding = metadata.get("forwarding")

        if forwarding:
            labels.append(
                ClassificationLabel(
                    name="forwarded",
                    category="message_origin",
                    confidence=1.0,
                )
            )

        return tuple(labels)

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Extract and classify message metadata."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Metadata classifier is disabled.",
            )

        try:
            metadata = self._build_metadata(
                classification_input
            )

            labels = self.filter_by_confidence(
                self._build_labels(metadata)
            )

            primary_label = labels[0] if labels else None

            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            return ClassificationResult(
                classifier=self.name,
                status=ClassificationStatus.COMPLETED,
                labels=labels,
                primary_label=primary_label,
                confidence=(
                    primary_label.confidence
                    if primary_label
                    else 0.0
                ),
                processing_time_ms=elapsed_ms,
                metadata=metadata,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Metadata classification failed",
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
