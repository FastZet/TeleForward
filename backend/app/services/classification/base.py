"""
TeleForward classification base module.

Defines common data structures and interfaces for message classifiers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Sequence


MAX_CONTENT_LENGTH = 100_000
MAX_LABEL_LENGTH = 128
MAX_LABELS = 100


class ClassificationStatus(StrEnum):
    """Status of a classification operation."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ClassificationInput:
    """Normalised input supplied to a classifier."""

    message_id: int
    account_id: int

    text: str = ""
    caption: str = ""

    media_type: str | None = None
    sender_id: int | None = None
    chat_id: int | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            isinstance(self.message_id, bool)
            or not isinstance(self.message_id, int)
            or self.message_id <= 0
        ):
            raise ValueError("message_id must be a positive integer.")

        if (
            isinstance(self.account_id, bool)
            or not isinstance(self.account_id, int)
            or self.account_id <= 0
        ):
            raise ValueError("account_id must be a positive integer.")

        if not isinstance(self.text, str):
            raise TypeError("text must be a string.")

        if not isinstance(self.caption, str):
            raise TypeError("caption must be a string.")

        if len(self.text) > MAX_CONTENT_LENGTH:
            raise ValueError("Message text exceeds the maximum length.")

        if len(self.caption) > MAX_CONTENT_LENGTH:
            raise ValueError("Message caption exceeds the maximum length.")

        for field_name in ("sender_id", "chat_id"):
            value = getattr(self, field_name)

            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(
                    f"{field_name} must be a positive integer or None."
                )

        if self.media_type is not None and not isinstance(
            self.media_type, str
        ):
            raise TypeError("media_type must be a string or None.")

        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary.")


@dataclass(frozen=True, slots=True)
class ClassificationLabel:
    """A classification label and its associated confidence."""

    name: str
    confidence: float
    category: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("Label name must be a string.")

        if not self.name.strip() or len(self.name) > MAX_LABEL_LENGTH:
            raise ValueError(
                f"Label name must contain 1-{MAX_LABEL_LENGTH} characters."
            )

        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError(
                "Label confidence must be between 0 and 1."
            )

        if self.category is not None and (
            not isinstance(self.category, str)
            or not self.category.strip()
            or len(self.category) > MAX_LABEL_LENGTH
        ):
            raise ValueError("Invalid classification category.")


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Standardised output from a classifier."""

    classifier: str
    status: ClassificationStatus

    labels: tuple[ClassificationLabel, ...] = ()
    primary_label: str | None = None

    confidence: float | None = None
    processing_time_ms: float | None = None

    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.classifier, str) or not (
            self.classifier.strip()
        ):
            raise ValueError("classifier cannot be empty.")

        if not isinstance(self.status, ClassificationStatus):
            raise ValueError("Invalid classification status.")

        if not isinstance(self.labels, tuple):
            raise TypeError("labels must be a tuple.")

        if len(self.labels) > MAX_LABELS:
            raise ValueError("Too many classification labels.")

        if any(
            not isinstance(label, ClassificationLabel)
            for label in self.labels
        ):
            raise TypeError(
                "Every label must be a ClassificationLabel instance."
            )

        if self.primary_label is not None:
            if not isinstance(self.primary_label, str) or not (
                self.primary_label.strip()
            ):
                raise ValueError("primary_label cannot be empty.")

        if (
            self.confidence is not None
            and (
                isinstance(self.confidence, bool)
                or not isinstance(self.confidence, (int, float))
                or not 0.0 <= self.confidence <= 1.0
            )
        ):
            raise ValueError(
                "confidence must be between 0 and 1."
            )

        if (
            self.processing_time_ms is not None
            and (
                isinstance(self.processing_time_ms, bool)
                or not isinstance(self.processing_time_ms, (int, float))
                or self.processing_time_ms < 0
            )
        ):
            raise ValueError(
                "processing_time_ms must be non-negative."
            )

        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary.")

        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string or None.")

        if self.created_at is not None:
            if (
                not isinstance(self.created_at, datetime)
                or self.created_at.tzinfo is None
                or self.created_at.utcoffset() is None
            ):
                raise ValueError(
                    "created_at must be a timezone-aware datetime."
                )

        if self.status == ClassificationStatus.FAILED and not self.error:
            raise ValueError(
                "Failed classifications must include an error."
            )

        if self.status != ClassificationStatus.FAILED and self.error:
            raise ValueError(
                "Only failed classifications may include an error."
            )


class BaseClassifier(ABC):
    """
    Abstract base class for all message classifiers.

    Subclasses implement classify() and return a ClassificationResult.
    """

    name: str = "base"
    version: str = "1.0.0"

    def __init__(
        self,
        *,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean.")

        if (
            isinstance(minimum_confidence, bool)
            or not isinstance(minimum_confidence, (int, float))
            or not 0.0 <= minimum_confidence <= 1.0
        ):
            raise ValueError(
                "minimum_confidence must be between 0 and 1."
            )

        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Classifier name cannot be empty.")

        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("Classifier version cannot be empty.")

        self.enabled = enabled
        self.minimum_confidence = float(minimum_confidence)

    @abstractmethod
    async def classify(
        self,
        message: ClassificationInput,
    ) -> ClassificationResult:
        """Classify a single Telegram message."""
        raise NotImplementedError

    async def classify_many(
        self,
        messages: Sequence[ClassificationInput],
    ) -> list[ClassificationResult]:
        """Classify multiple messages sequentially."""
        if not self.enabled:
            return [
                self.skipped_result("Classifier is disabled.")
                for _ in messages
            ]

        results: list[ClassificationResult] = []

        for message in messages:
            results.append(await self.classify(message))

        return results

    def skipped_result(
        self,
        reason: str,
    ) -> ClassificationResult:
        """Create a standard skipped-classification result."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A skip reason must be provided.")

        return ClassificationResult(
            classifier=self.name,
            status=ClassificationStatus.SKIPPED,
            metadata={"reason": reason},
        )

    def filter_by_confidence(
        self,
        labels: Sequence[ClassificationLabel],
    ) -> tuple[ClassificationLabel, ...]:
        """Remove labels below the configured confidence threshold."""
        return tuple(
            label
            for label in labels
            if label.confidence >= self.minimum_confidence
        )

    def build_result(
        self,
        labels: Sequence[ClassificationLabel],
        *,
        processing_time_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ClassificationResult:
        """Build a standard result from classifier labels."""
        filtered_labels = self.filter_by_confidence(labels)

        ordered_labels = tuple(
            sorted(
                filtered_labels,
                key=lambda label: label.confidence,
                reverse=True,
            )
        )

        primary_label = (
            ordered_labels[0].name
            if ordered_labels
            else None
        )

        confidence = (
            ordered_labels[0].confidence
            if ordered_labels
            else None
        )

        return ClassificationResult(
            classifier=self.name,
            status=ClassificationStatus.COMPLETED,
            labels=ordered_labels,
            primary_label=primary_label,
            confidence=confidence,
            processing_time_ms=processing_time_ms,
            metadata=metadata or {},
        )
