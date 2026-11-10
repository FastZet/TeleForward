"""
TeleForward prefix and suffix transformation.

Adds configurable text before and after Telegram message content.

Supports:
- Independent text and caption processing
- Prefixes and suffixes
- Optional separators
- Template variables
- Conditional application
- Configurable whitespace handling
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

MAX_TEMPLATE_LENGTH = 4_096
MAX_TEMPLATE_VARIABLES = 50

ALLOWED_TEMPLATE_VARIABLES = frozenset({
    "message_id",
    "account_id",
    "chat_id",
    "sender_id",
    "media_type",
})


class PrefixSuffixTransformation(BaseTransformation):
    """Add prefixes and suffixes to message text and captions."""

    name = "prefix_suffix"
    version = "1.0.0"

    def __init__(
        self,
        *,
        prefix: str = "",
        suffix: str = "",
        text_prefix: str | None = None,
        text_suffix: str | None = None,
        caption_prefix: str | None = None,
        caption_suffix: str | None = None,
        separator: str = "",
        apply_to_text: bool = True,
        apply_to_caption: bool = True,
        skip_empty_content: bool = True,
        strip_content: bool = False,
        variables_enabled: bool = False,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)

        for name, value in (
            ("prefix", prefix),
            ("suffix", suffix),
            ("separator", separator),
        ):
            self._validate_template(value, name)

        overrides = {
            "text_prefix": text_prefix,
            "text_suffix": text_suffix,
            "caption_prefix": caption_prefix,
            "caption_suffix": caption_suffix,
        }

        for name, value in overrides.items():
            if value is not None:
                self._validate_template(value, name)

        for name, value in (
            ("apply_to_text", apply_to_text),
            ("apply_to_caption", apply_to_caption),
            ("skip_empty_content", skip_empty_content),
            ("strip_content", strip_content),
            ("variables_enabled", variables_enabled),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean.")

        self.prefix = prefix
        self.suffix = suffix

        self.text_prefix = (
            prefix if text_prefix is None else text_prefix
        )
        self.text_suffix = (
            suffix if text_suffix is None else text_suffix
        )
        self.caption_prefix = (
            prefix if caption_prefix is None else caption_prefix
        )
        self.caption_suffix = (
            suffix if caption_suffix is None else caption_suffix
        )

        self.separator = separator
        self.apply_to_text = apply_to_text
        self.apply_to_caption = apply_to_caption
        self.skip_empty_content = skip_empty_content
        self.strip_content = strip_content
        self.variables_enabled = variables_enabled

    @staticmethod
    def _validate_template(
        value: str,
        name: str,
    ) -> None:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string.")

        if len(value) > MAX_TEMPLATE_LENGTH:
            raise ValueError(
                f"{name} cannot exceed {MAX_TEMPLATE_LENGTH} characters."
            )

    def _build_variables(
        self,
        transformation_input: TransformationInput,
    ) -> dict[str, str]:
        """Build the supported template-variable mapping."""
        return {
            "message_id": str(transformation_input.message_id),
            "account_id": str(transformation_input.account_id),
            "chat_id": str(transformation_input.chat_id),
            "sender_id": (
                str(transformation_input.sender_id)
                if transformation_input.sender_id is not None
                else ""
            ),
            "media_type": transformation_input.media_type or "",
        }

    def _render_template(
        self,
        template: str,
        variables: Mapping[str, str],
    ) -> str:
        """Render only explicitly supported template variables."""
        if not self.variables_enabled or not template:
            return template

        def replace(match: re.Match[str]) -> str:
            variable = match.group(1)

            if variable not in ALLOWED_TEMPLATE_VARIABLES:
                raise ValueError(
                    f"Unsupported template variable: {variable}"
                )

            return variables[variable]

        return re.sub(
            r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}",
            replace,
            template,
        )

    def _apply(
        self,
        content: str,
        *,
        prefix: str,
        suffix: str,
        variables: Mapping[str, str],
    ) -> str:
        """Apply prefix and suffix to a content string."""
        if self.strip_content:
            content = content.strip()

        if self.skip_empty_content and not content.strip():
            return content

        rendered_prefix = self._render_template(
            prefix,
            variables,
        )
        rendered_suffix = self._render_template(
            suffix,
            variables,
        )

        if not rendered_prefix and not rendered_suffix:
            return content

        if rendered_prefix and content:
            content = rendered_prefix + self.separator + content

        elif rendered_prefix:
            content = rendered_prefix

        if rendered_suffix and content:
            content = content + self.separator + rendered_suffix

        elif rendered_suffix:
            content = rendered_suffix

        return content

    async def transform(
        self,
        transformation_input: TransformationInput,
    ) -> TransformationOutput:
        """Apply configured prefixes and suffixes."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                transformation_input,
                reason="Prefix/suffix transformation is disabled.",
            )

        try:
            variables = self._build_variables(
                transformation_input
            )

            text = transformation_input.text
            caption = transformation_input.caption

            if self.apply_to_text:
                text = self._apply(
                    text,
                    prefix=self.text_prefix,
                    suffix=self.text_suffix,
                    variables=variables,
                )

            if self.apply_to_caption:
                caption = self._apply(
                    caption,
                    prefix=self.caption_prefix,
                    suffix=self.caption_suffix,
                    variables=variables,
                )

            return self.build_result(
                transformation_input,
                text=text,
                caption=caption,
                metadata={
                    "text_processed": self.apply_to_text,
                    "caption_processed": self.apply_to_caption,
                    "prefix_applied": bool(
                        self.text_prefix or self.caption_prefix
                    ),
                    "suffix_applied": bool(
                        self.text_suffix or self.caption_suffix
                    ),
                    "template_variables_enabled": self.variables_enabled,
                },
                started_at=started_at,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Prefix/suffix transformation failed",
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
