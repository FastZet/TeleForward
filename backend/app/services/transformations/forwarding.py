"""
TeleForward forwarding transformation.

Adds source attribution and forwarding context to messages before
they are passed to the forwarding delivery service.

This module does not perform Telegram API forwarding operations.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Mapping
from typing import Any

from app.services.transformations.base import (
    BaseTransformation,
    TransformationInput,
    TransformationOutput,
    TransformationStatus,
)

logger = logging.getLogger(__name__)

MAX_TEMPLATE_LENGTH = 2048
MAX_ATTRIBUTION_LENGTH = 4096
MAX_METADATA_FIELDS = 100

TEMPLATE_PATTERN = re.compile(
    r"\{([a-zA-Z][a-zA-Z0-9_.-]{0,127})\}"
)

ALLOWED_TEMPLATE_FIELDS = frozenset({
    "source_chat_title",
    "source_chat_id",
    "source_message_id",
    "source_sender_name",
    "source_sender_id",
    "source_date",
    "original_forward_date",
    "destination_chat_title",
    "destination_chat_id",
    "message_id",
    "account_id",
    "chat_id",
    "media_type",
})


class ForwardingTransformation(BaseTransformation):
    """Add source attribution and forwarding metadata."""

    name = "forwarding"
    version = "1.0.0"

    def __init__(
        self,
        *,
        attribution_template: str | None = None,
        placement: str = "suffix",
        separator: str = "\n\n",
        apply_to_text: bool = True,
        apply_to_caption: bool = True,
        include_source_metadata: bool = True,
        preserve_existing_attribution: bool = True,
        require_source_metadata: bool = False,
        metadata_prefix: str = "forwarding",
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)

        if placement not in {"prefix", "suffix"}:
            raise ValueError(
                "placement must be either 'prefix' or 'suffix'."
            )

        boolean_options = {
            "apply_to_text": apply_to_text,
            "apply_to_caption": apply_to_caption,
            "include_source_metadata": include_source_metadata,
            "preserve_existing_attribution": (
                preserve_existing_attribution
            ),
            "require_source_metadata": require_source_metadata,
        }

        for name, value in boolean_options.items():
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean.")

        if not isinstance(separator, str):
            raise TypeError("separator must be a string.")

        if len(separator) > 100:
            raise ValueError("separator is too long.")

        if not isinstance(metadata_prefix, str):
            raise TypeError("metadata_prefix must be a string.")

        if not re.fullmatch(
            r"[a-zA-Z][a-zA-Z0-9_-]{0,63}",
            metadata_prefix,
        ):
            raise ValueError("Invalid metadata_prefix.")

        if attribution_template is not None:
            if not isinstance(attribution_template, str):
                raise TypeError(
                    "attribution_template must be a string or None."
                )

            if len(attribution_template) > MAX_TEMPLATE_LENGTH:
                raise ValueError(
                    "Attribution template is too long."
                )

            self._validate_template(attribution_template)

        self.attribution_template = attribution_template
        self.placement = placement
        self.separator = separator
        self.apply_to_text = apply_to_text
        self.apply_to_caption = apply_to_caption
        self.include_source_metadata = include_source_metadata
        self.preserve_existing_attribution = (
            preserve_existing_attribution
        )
        self.require_source_metadata = require_source_metadata
        self.metadata_prefix = metadata_prefix

    @staticmethod
    def _validate_template(template: str) -> None:
        """Reject unsupported template variables."""
        for field in TEMPLATE_PATTERN.findall(template):
            if field not in ALLOWED_TEMPLATE_FIELDS:
                raise ValueError(
                    f"Unsupported attribution variable: {field}"
                )

    @staticmethod
    def _stringify(value: Any) -> str:
        """Convert supported metadata values to display strings."""
        if value is None:
            return ""

        if isinstance(value, (str, int, float, bool)):
            return str(value)

        return ""

    @staticmethod
    def _build_context(
        transformation_input: TransformationInput,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Build the restricted attribution template context."""
        context = {
            key: metadata.get(key)
            for key in ALLOWED_TEMPLATE_FIELDS
        }

        context.update({
            "message_id": transformation_input.message_id,
            "account_id": transformation_input.account_id,
            "chat_id": transformation_input.chat_id,
            "media_type": transformation_input.media_type,
        })

        return context

    def _render_attribution(
        self,
        transformation_input: TransformationInput,
        metadata: Mapping[str, Any],
    ) -> str | None:
        """Render the configured source attribution."""
        if self.attribution_template is None:
            return None

        context = self._build_context(
            transformation_input,
            metadata,
        )

        def replace(match: re.Match[str]) -> str:
            field = match.group(1)
            return self._stringify(context.get(field))

        rendered = TEMPLATE_PATTERN.sub(
            replace,
            self.attribution_template,
        ).strip()

        if not rendered:
            return None

        if len(rendered) > MAX_ATTRIBUTION_LENGTH:
            raise ValueError(
                "Rendered attribution exceeds the maximum length."
            )

        return rendered

    def _apply_attribution(
        self,
        content: str,
        attribution: str | None,
    ) -> str:
        """Add attribution to content according to placement."""
        if not attribution:
            return content

        if not content:
            return attribution

        if (
            self.preserve_existing_attribution
            and attribution in content
        ):
            return content

        if self.placement == "prefix":
            return attribution + self.separator + content

        return content + self.separator + attribution

    def _build_forwarding_metadata(
        self,
        metadata: Mapping[str, Any],
        attribution: str | None,
    ) -> dict[str, Any]:
        """Preserve existing metadata and add forwarding context."""
        result = dict(metadata)

        if len(result) > MAX_METADATA_FIELDS:
            raise ValueError(
                "Input metadata exceeds the permitted field count."
            )

        if self.include_source_metadata:
            result[f"{self.metadata_prefix}_attribution"] = attribution
            result[f"{self.metadata_prefix}_placement"] = self.placement

            source_fields = (
                "source_chat_title",
                "source_chat_id",
                "source_message_id",
                "source_sender_name",
                "source_sender_id",
                "source_date",
                "original_forward_date",
            )

            source_context = {
                key: metadata[key]
                for key in source_fields
                if key in metadata
            }

            result[f"{self.metadata_prefix}_source"] = source_context

        if len(result) > MAX_METADATA_FIELDS:
            raise ValueError(
                "Forwarding metadata exceeds the permitted field count."
            )

        return result

    async def transform(
        self,
        transformation_input: TransformationInput,
    ) -> TransformationOutput:
        """Apply forwarding attribution and metadata transformations."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                transformation_input,
                reason="Forwarding transformation is disabled.",
            )

        try:
            original_metadata = dict(
                transformation_input.metadata or {}
            )

            if self.require_source_metadata:
                if not any(
                    original_metadata.get(key) is not None
                    for key in (
                        "source_chat_title",
                        "source_chat_id",
                        "source_message_id",
                        "source_sender_name",
                    )
                ):
                    raise ValueError(
                        "Source metadata is required but unavailable."
                    )

            attribution = self._render_attribution(
                transformation_input,
                original_metadata,
            )

            text = transformation_input.text
            caption = transformation_input.caption

            if self.apply_to_text:
                text = self._apply_attribution(
                    text,
                    attribution,
                )

            if self.apply_to_caption:
                caption = self._apply_attribution(
                    caption,
                    attribution,
                )

            metadata = self._build_forwarding_metadata(
                original_metadata,
                attribution,
            )

            return self.build_result(
                transformation_input,
                text=text,
                caption=caption,
                metadata=metadata,
                started_at=started_at,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Forwarding transformation failed",
                extra={
                    "message_id": transformation_input.message_id,
                },
            )

            return TransformationOutput(
                transformation=self.name,
                status=TransformationStatus.FAILED,
                text=transformation_input.text,
                caption=transformation_input.caption,
                changed=False,
                processing_time_ms=elapsed_ms,
                error=str(exc)[:2000],
                metadata={
                    "error_type": type(exc).__name__,
                },
            )
