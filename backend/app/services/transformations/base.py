"""
TeleForward transformation base interfaces.

Defines common input/output structures and the abstract base class
used by individual message transformation implementations.
"""

from __future__ import annotations

import logging
import time

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 100_000
MAX_CAPTION_LENGTH = 4_096
MAX_TRANSFORMATIONS = 100
MAX_TRANSFORMATION_NAME_LENGTH = 128
MAX_METADATA_FIELDS = 200


class TransformationStatus(StrEnum):
    """Execution status of a transformation."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TransformationInput:
    """
    Immutable representation of a message to transform.

    The input represents the content available to the transformation
    pipeline, not the complete Telegram message object.
    """

    message_id: int
    account_id: int
    chat_id: int
    text: str = ""
    caption: str = ""
    media_type: str | None = None
    sender_id: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "message_id",
            "account_id",
            "chat_id",
        ):
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(
                    f"{name} must be a positive integer."
                )

        if self.sender_id is not None and (
            isinstance(self.sender_id, bool)
            or not isinstance(self.sender_id, int)
            or self.sender_id <= 0
        ):
            raise ValueError(
                "sender_id must be a positive integer or None."
            )

        if not isinstance(self.text, str):
            raise TypeError("text must be a string.")

        if not isinstance(self.caption, str):
            raise TypeError("caption must be a string.")

        if len(self.text) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"text cannot exceed {MAX_MESSAGE_LENGTH} characters."
            )

        if len(self.caption) > MAX_CAPTION_LENGTH:
            raise ValueError(
                f"caption cannot exceed {MAX_CAPTION_LENGTH} characters."
            )

        if self.media_type is not None:
            if not isinstance(self.media_type, str):
                raise TypeError(
                    "media_type must be a string or None."
                )

            if len(self.media_type) > 128:
                raise ValueError(
                    "media_type cannot exceed 128 characters."
                )

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        if len(self.metadata) > MAX_METADATA_FIELDS:
            raise ValueError(
                f"metadata cannot contain more than "
                f"{MAX_METADATA_FIELDS} top-level fields."
            )


@dataclass(frozen=True, slots=True)
class TransformationOutput:
    """
    Result produced by an individual transformation.

    The output contains transformed content and execution metadata.
    """

    transformation: str
    status: TransformationStatus
    text: str
    caption: str
    changed: bool = False
    processing_time_ms: float = 0.0
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not isinstance(self.transformation, str):
            raise TypeError("transformation must be a string.")

        if not self.transformation.strip():
            raise ValueError("transformation cannot be empty.")

        if len(self.transformation) > MAX_TRANSFORMATION_NAME_LENGTH:
            raise ValueError(
                "transformation name is too long."
            )

        if not isinstance(self.status, TransformationStatus):
            raise TypeError(
                "status must be a TransformationStatus."
            )

        if not isinstance(self.text, str):
            raise TypeError("text must be a string.")

        if not isinstance(self.caption, str):
            raise TypeError("caption must be a string.")

        if len(self.text) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"text cannot exceed {MAX_MESSAGE_LENGTH} characters."
            )

        if len(self.caption) > MAX_CAPTION_LENGTH:
            raise ValueError(
                f"caption cannot exceed {MAX_CAPTION_LENGTH} characters."
            )

        if not isinstance(self.changed, bool):
            raise TypeError("changed must be a boolean.")

        if (
            isinstance(self.processing_time_ms, bool)
            or not isinstance(
                self.processing_time_ms,
                (int, float),
            )
            or self.processing_time_ms < 0
        ):
            raise ValueError(
                "processing_time_ms must be a non-negative number."
            )

        if self.status == TransformationStatus.FAILED:
            if not self.error:
                raise ValueError(
                    "Failed transformations must include an error."
                )

        elif self.error is not None:
            raise ValueError(
                "Only failed transformations may contain an error."
            )

        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping.")

        if len(self.metadata) > MAX_METADATA_FIELDS:
            raise ValueError(
                "Transformation metadata contains too many fields."
            )

        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be a datetime.")

        if (
            self.created_at.tzinfo is None
            or self.created_at.utcoffset() is None
        ):
            raise ValueError(
                "created_at must be timezone-aware."
            )


class BaseTransformation(ABC):
    """
    Abstract base class for message transformations.

    Subclasses implement transform() and return a
    TransformationOutput instance.
    """

    name: str = "base"
    version: str = "1.0.0"

    def __init__(
        self,
        *,
        enabled: bool = True,
    ) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean.")

        self.enabled = enabled

    @abstractmethod
    async def transform(
        self,
        transformation_input: TransformationInput,
    ) -> TransformationOutput:
        """Execute the transformation."""

    def skipped_result(
        self,
        transformation_input: TransformationInput,
        *,
        reason: str,
    ) -> TransformationOutput:
        """Return an unchanged result for a skipped transformation."""
        return TransformationOutput(
            transformation=self.name,
            status=TransformationStatus.SKIPPED,
            text=transformation_input.text,
            caption=transformation_input.caption,
            changed=False,
            metadata={
                "reason": reason,
            },
        )

    def build_result(
        self,
        transformation_input: TransformationInput,
        *,
        text: str | None = None,
        caption: str | None = None,
        status: TransformationStatus = TransformationStatus.COMPLETED,
        metadata: Mapping[str, Any] | None = None,
        started_at: float | None = None,
    ) -> TransformationOutput:
        """Construct a validated transformation result."""
        output_text = (
            transformation_input.text
            if text is None
            else text
        )

        output_caption = (
            transformation_input.caption
            if caption is None
            else caption
        )

        if not isinstance(output_text, str):
            raise TypeError("Transformed text must be a string.")

        if not isinstance(output_caption, str):
            raise TypeError("Transformed caption must be a string.")

        processing_time_ms = (
            max(0.0, (time.perf_counter() - started_at) * 1000)
            if started_at is not None
            else 0.0
        )

        return TransformationOutput(
            transformation=self.name,
            status=status,
            text=output_text,
            caption=output_caption,
            changed=(
                output_text != transformation_input.text
                or output_caption != transformation_input.caption
            ),
            processing_time_ms=processing_time_ms,
            metadata=dict(metadata or {}),
        )

    def validate_text(
        self,
        text: str,
        *,
        maximum_length: int = MAX_MESSAGE_LENGTH,
    ) -> str:
        """Validate transformed text against length limits."""
        if not isinstance(text, str):
            raise TypeError("text must be a string.")

        if (
            isinstance(maximum_length, bool)
            or not isinstance(maximum_length, int)
            or maximum_length < 0
        ):
            raise ValueError(
                "maximum_length must be a non-negative integer."
            )

        if len(text) > maximum_length:
            raise ValueError(
                f"Text exceeds the maximum length of "
                f"{maximum_length} characters."
            )

        return text

    def validate_configuration(
        self,
        configuration: Mapping[str, Any],
    ) -> dict[str, Any]:
        """
        Validate and copy a transformation configuration.

        Individual transformation classes should override this
        method to enforce their own configuration schemas.
        """
        if not isinstance(configuration, Mapping):
            raise TypeError(
                "configuration must be a mapping."
            )

        if len(configuration) > MAX_METADATA_FIELDS:
            raise ValueError(
                "configuration contains too many fields."
            )

        return dict(configuration)
