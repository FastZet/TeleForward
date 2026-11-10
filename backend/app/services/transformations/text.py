"""
TeleForward text transformation service.

Provides configurable text and caption cleanup operations.

Supported operations:
- Unicode normalisation
- Leading and trailing whitespace removal
- Whitespace collapsing
- Line-break normalisation
- Empty-line removal
- Control-character removal
- Optional zero-width character removal
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata

from app.services.transformations.base import (
    BaseTransformation,
    TransformationInput,
    TransformationOutput,
    TransformationStatus,
)


logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 100_000


class TextTransformation(BaseTransformation):
    """Clean and normalise Telegram message text and captions."""

    name = "text"
    version = "1.0.0"

    def __init__(
        self,
        *,
        unicode_normalisation: str = "NFKC",
        strip_whitespace: bool = True,
        collapse_spaces: bool = False,
        normalise_line_breaks: bool = True,
        remove_empty_lines: bool = False,
        remove_control_characters: bool = True,
        remove_zero_width_characters: bool = False,
        preserve_line_breaks: bool = True,
        apply_to_text: bool = True,
        apply_to_caption: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)

        if unicode_normalisation not in {
            "NFC",
            "NFD",
            "NFKC",
            "NFKD",
            "none",
        }:
            raise ValueError(
                "Unsupported Unicode normalisation form."
            )

        boolean_options = {
            "strip_whitespace": strip_whitespace,
            "collapse_spaces": collapse_spaces,
            "normalise_line_breaks": normalise_line_breaks,
            "remove_empty_lines": remove_empty_lines,
            "remove_control_characters": remove_control_characters,
            "remove_zero_width_characters": remove_zero_width_characters,
            "preserve_line_breaks": preserve_line_breaks,
            "apply_to_text": apply_to_text,
            "apply_to_caption": apply_to_caption,
        }

        for name, value in boolean_options.items():
            if not isinstance(value, bool):
                raise ValueError(
                    f"{name} must be a boolean."
                )

        self.unicode_normalisation = unicode_normalisation
        self.strip_whitespace = strip_whitespace
        self.collapse_spaces = collapse_spaces
        self.normalise_line_breaks = normalise_line_breaks
        self.remove_empty_lines = remove_empty_lines
        self.remove_control_characters = remove_control_characters
        self.remove_zero_width_characters = remove_zero_width_characters
        self.preserve_line_breaks = preserve_line_breaks
        self.apply_to_text = apply_to_text
        self.apply_to_caption = apply_to_caption

    def _normalise_unicode(self, value: str) -> str:
        """Apply the configured Unicode normalisation."""
        if self.unicode_normalisation == "none":
            return value

        return unicodedata.normalize(
            self.unicode_normalisation,
            value,
        )

    def _normalise_line_endings(self, value: str) -> str:
        """Convert common line-ending formats to LF."""
        if not self.normalise_line_breaks:
            return value

        return (
            value
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\u0085", "\n")
            .replace("\u2028", "\n")
            .replace("\u2029", "\n")
        )

    def _remove_control_characters(self, value: str) -> str:
        """Remove Unicode control characters while preserving layout."""
        if not self.remove_control_characters:
            return value

        result: list[str] = []

        for character in value:
            category = unicodedata.category(character)

            if category != "Cc":
                result.append(character)
                continue

            if character == "\n" and self.preserve_line_breaks:
                result.append(character)

            elif character == "\t" and self.preserve_line_breaks:
                result.append(" ")

        return "".join(result)

    def _remove_zero_width(self, value: str) -> str:
        """Optionally remove selected invisible formatting characters."""
        if not self.remove_zero_width_characters:
            return value

        excluded = {
            "\u200b",  # Zero-width space
            "\u200c",  # Zero-width non-joiner
            "\u200d",  # Zero-width joiner
            "\ufeff",  # Byte order mark
        }

        return "".join(
            character
            for character in value
            if character not in excluded
        )

    def _collapse_whitespace(self, value: str) -> str:
        """Collapse repeated horizontal whitespace."""
        if not self.collapse_spaces:
            return value

        if self.preserve_line_breaks:
            lines = value.split("\n")

            return "\n".join(
                re.sub(r"[^\S\n]+", " ", line)
                for line in lines
            )

        return re.sub(r"\s+", " ", value)

    def _remove_empty_lines(self, value: str) -> str:
        """Remove blank lines while preserving non-empty line order."""
        if not self.remove_empty_lines:
            return value

        lines = [
            line
            for line in value.split("\n")
            if line.strip()
        ]

        return "\n".join(lines)

    def _transform_content(self, value: str) -> str:
        """Apply all configured text transformations."""
        if len(value) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"Input exceeds {MAX_TEXT_LENGTH} characters."
            )

        result = self._normalise_unicode(value)
        result = self._normalise_line_endings(result)
        result = self._remove_control_characters(result)
        result = self._remove_zero_width(result)
        result = self._collapse_whitespace(result)
        result = self._remove_empty_lines(result)

        if self.strip_whitespace:
            result = result.strip()

        return result

    async def transform(
        self,
        transformation_input: TransformationInput,
    ) -> TransformationOutput:
        """Transform message text and caption."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                transformation_input,
                reason="Text transformation is disabled.",
            )

        try:
            text = transformation_input.text
            caption = transformation_input.caption

            if self.apply_to_text:
                text = self._transform_content(text)

            if self.apply_to_caption:
                caption = self._transform_content(caption)

            return self.build_result(
                transformation_input,
                text=text,
                caption=caption,
                metadata={
                    "unicode_normalisation": self.unicode_normalisation,
                    "text_processed": self.apply_to_text,
                    "caption_processed": self.apply_to_caption,
                    "strip_whitespace": self.strip_whitespace,
                    "collapse_spaces": self.collapse_spaces,
                    "remove_empty_lines": self.remove_empty_lines,
                },
                started_at=started_at,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Text transformation failed",
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
