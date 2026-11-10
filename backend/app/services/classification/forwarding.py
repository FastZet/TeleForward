"""
TeleForward forwarding classifier.

Classifies Telegram messages using forwarding-related metadata.

This classifier does not execute forwarding operations or verify
destination permissions. It only interprets metadata supplied by
the Telegram integration layer.
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

MAX_METADATA_FIELDS = 200

FORWARD_SOURCE_KEYS = (
    "forwarded_from",
    "forwarded_from_id",
    "forwarded_from_name",
    "forward_from",
    "forward_from_id",
    "forward_from_name",
    "fwd_from",
)

PROTECTION_KEYS = (
    "noforwards",
    "no_forwards",
    "protected_content",
    "has_protected_content",
    "is_protected",
)

FORWARDING_STATUS_KEYS = (
    "forwarded",
    "is_forwarded",
    "forwarded_message",
)


class ForwardingClassifier(BaseClassifier):
    """
    Classify forwarding-related message attributes.

    Classification categories:

    - forwarding_status: original or forwarded
    - forwarding_eligibility: protected, unrestricted or unknown
    - forwarding_source: source information availability

    Eligibility is metadata-based and must not be treated as a
    substitute for Telegram API permission checks.
    """

    name = "forwarding"
    version = "1.0.0"

    def __init__(
        self,
        *,
        classify_forwarding_status: bool = True,
        classify_protection: bool = True,
        classify_source: bool = True,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        for name, value in (
            (
                "classify_forwarding_status",
                classify_forwarding_status,
            ),
            ("classify_protection", classify_protection),
            ("classify_source", classify_source),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean.")

        self.classify_forwarding_status = (
            classify_forwarding_status
        )
        self.classify_protection = classify_protection
        self.classify_source = classify_source

    @staticmethod
    def _get_first_present(
        metadata: Mapping[str, Any],
        keys: tuple[str, ...],
    ) -> tuple[bool, Any]:
        """Return the first explicitly present metadata value."""
        for key in keys:
            if key in metadata:
                return True, metadata[key]

        return False, None

    @staticmethod
    def _parse_boolean(value: Any) -> bool | None:
        """
        Interpret explicitly supplied boolean metadata.

        Unknown values remain unknown rather than being interpreted
        as False.
        """
        if isinstance(value, bool):
            return value

        if isinstance(value, int) and value in (0, 1):
            return bool(value)

        if isinstance(value, str):
            normalised = value.strip().casefold()

            if normalised in {"true", "yes", "1", "enabled"}:
                return True

            if normalised in {"false", "no", "0", "disabled"}:
                return False

        return None

    @staticmethod
    def _has_forward_source(
        metadata: Mapping[str, Any],
    ) -> bool:
        """Determine whether source information is present."""
        for key in FORWARD_SOURCE_KEYS:
            value = metadata.get(key)

            if value is None:
                continue

            if isinstance(value, str) and not value.strip():
                continue

            return True

        return False

    def _classify_forwarding_status(
        self,
        metadata: Mapping[str, Any],
    ) -> tuple[ClassificationLabel | None, str]:
        """Determine whether the message is forwarded."""
        present, value = self._get_first_present(
            metadata,
            FORWARDING_STATUS_KEYS,
        )

        if present:
            forwarded = self._parse_boolean(value)

            if forwarded is not None:
                return (
                    ClassificationLabel(
                        name=(
                            "forwarded"
                            if forwarded
                            else "original"
                        ),
                        category="forwarding_status",
                        confidence=1.0,
                    ),
                    "explicit_status",
                )

        if self._has_forward_source(metadata):
            return (
                ClassificationLabel(
                    name="forwarded",
                    category="forwarding_status",
                    confidence=0.95,
                ),
                "source_metadata",
            )

        return None, "unknown"

    def _classify_protection(
        self,
        metadata: Mapping[str, Any],
    ) -> tuple[ClassificationLabel | None, str]:
        """Determine whether forwarding restrictions are indicated."""
        present, value = self._get_first_present(
            metadata,
            PROTECTION_KEYS,
        )

        if not present:
            return None, "unknown"

        protected = self._parse_boolean(value)

        if protected is None:
            return None, "unknown"

        if protected:
            return (
                ClassificationLabel(
                    name="protected",
                    category="forwarding_eligibility",
                    confidence=1.0,
                ),
                "explicit_protection",
            )

        return (
            ClassificationLabel(
                name="unrestricted_by_metadata",
                category="forwarding_eligibility",
                confidence=1.0,
            ),
            "explicit_unprotected_status",
        )

    def _classify_source(
        self,
        metadata: Mapping[str, Any],
    ) -> ClassificationLabel:
        """Determine whether forwarding source information exists."""
        return ClassificationLabel(
            name=(
                "source_available"
                if self._has_forward_source(metadata)
                else "source_unavailable"
            ),
            category="forwarding_source",
            confidence=1.0,
        )

    def _build_metadata(
        self,
        classification_input: ClassificationInput,
        *,
        status_method: str,
        protection_method: str,
        is_protected: bool | None,
        is_forwarded: bool | None,
        source_available: bool,
    ) -> dict[str, Any]:
        """Build a structured forwarding classification result."""
        return {
            "message_id": classification_input.message_id,
            "account_id": classification_input.account_id,
            "chat_id": classification_input.chat_id,
            "is_forwarded": is_forwarded,
            "is_protected": is_protected,
            "source_available": source_available,
            "forwarding_status_detection": status_method,
            "protection_detection": protection_method,
            "metadata_fields_examined": min(
                len(classification_input.metadata),
                MAX_METADATA_FIELDS,
            ),
        }

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Classify forwarding-related message attributes."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Forwarding classifier is disabled.",
            )

        try:
            metadata = classification_input.metadata

            labels: list[ClassificationLabel] = []

            is_forwarded: bool | None = None
            is_protected: bool | None = None

            status_method = "not_checked"
            protection_method = "not_checked"

            if self.classify_forwarding_status:
                status_label, status_method = (
                    self._classify_forwarding_status(metadata)
                )

                if status_label is not None:
                    labels.append(status_label)
                    is_forwarded = (
                        status_label.name == "forwarded"
                    )

            if self.classify_protection:
                protection_label, protection_method = (
                    self._classify_protection(metadata)
                )

                if protection_label is not None:
                    labels.append(protection_label)
                    is_protected = (
                        protection_label.name == "protected"
                    )

            source_available = self._has_forward_source(
                metadata
            )

            if self.classify_source:
                labels.append(
                    self._classify_source(metadata)
                )

            filtered_labels = self.filter_by_confidence(
                labels
            )

            primary_label = (
                filtered_labels[0]
                if filtered_labels
                else None
            )

            result_metadata = self._build_metadata(
                classification_input,
                status_method=status_method,
                protection_method=protection_method,
                is_protected=is_protected,
                is_forwarded=is_forwarded,
                source_available=source_available,
            )

            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            return ClassificationResult(
                classifier=self.name,
                status=ClassificationStatus.COMPLETED,
                labels=filtered_labels,
                primary_label=primary_label,
                confidence=(
                    primary_label.confidence
                    if primary_label is not None
                    else 0.0
                ),
                processing_time_ms=elapsed_ms,
                metadata=result_metadata,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Forwarding classification failed",
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
