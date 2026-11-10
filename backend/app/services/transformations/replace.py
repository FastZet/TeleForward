"""
TeleForward text replacement transformation.

Supports literal and regular-expression substitutions on message
text and captions.
"""

from __future__ import annotations

import logging
import re
import time

from app.services.transformations.base import (
    BaseTransformation,
    TransformationInput,
    TransformationOutput,
    TransformationStatus,
)

logger = logging.getLogger(__name__)

MAX_PATTERNS = 100
MAX_PATTERN_LENGTH = 2_048
MAX_REPLACEMENT_LENGTH = 4_096
MAX_REPLACEMENTS_PER_PATTERN = 10_000


class ReplaceTransformation(BaseTransformation):
    """Replace configured text patterns in messages and captions."""

    name = "replace"
    version = "1.0.0"

    def __init__(
        self,
        *,
        replacements: dict[str, str] | None = None,
        patterns: list[dict[str, str]] | None = None,
        use_regex: bool = False,
        case_sensitive: bool = True,
        whole_word: bool = False,
        maximum_replacements: int = 0,
        apply_to_text: bool = True,
        apply_to_caption: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)

        if not isinstance(use_regex, bool):
            raise ValueError("use_regex must be a boolean.")

        if not isinstance(case_sensitive, bool):
            raise ValueError("case_sensitive must be a boolean.")

        if not isinstance(whole_word, bool):
            raise ValueError("whole_word must be a boolean.")

        if not isinstance(apply_to_text, bool):
            raise ValueError("apply_to_text must be a boolean.")

        if not isinstance(apply_to_caption, bool):
            raise ValueError("apply_to_caption must be a boolean.")

        if (
            isinstance(maximum_replacements, bool)
            or not isinstance(maximum_replacements, int)
            or maximum_replacements < 0
            or maximum_replacements > MAX_REPLACEMENTS_PER_PATTERN
        ):
            raise ValueError(
                "maximum_replacements must be between 0 and "
                f"{MAX_REPLACEMENTS_PER_PATTERN}."
            )

        if replacements is not None and patterns is not None:
            raise ValueError(
                "Provide either replacements or patterns, not both."
            )

        self.use_regex = use_regex
        self.case_sensitive = case_sensitive
        self.whole_word = whole_word
        self.maximum_replacements = maximum_replacements
        self.apply_to_text = apply_to_text
        self.apply_to_caption = apply_to_caption

        self.patterns = self._normalise_patterns(
            replacements=replacements,
            patterns=patterns,
        )

        self._compiled_patterns = self._compile_patterns()

    @staticmethod
    def _normalise_patterns(
        *,
        replacements: dict[str, str] | None,
        patterns: list[dict[str, str]] | None,
    ) -> list[tuple[str, str]]:
        """Validate and normalise replacement definitions."""
        if replacements is not None:
            if not isinstance(replacements, dict):
                raise TypeError("replacements must be a dictionary.")

            source = [
                {"pattern": key, "replacement": value}
                for key, value in replacements.items()
            ]

        elif patterns is not None:
            if not isinstance(patterns, list):
                raise TypeError("patterns must be a list.")

            source = patterns

        else:
            source = []

        if len(source) > MAX_PATTERNS:
            raise ValueError(
                f"At most {MAX_PATTERNS} replacement patterns are allowed."
            )

        normalised: list[tuple[str, str]] = []

        for index, item in enumerate(source):
            if not isinstance(item, dict):
                raise TypeError(
                    f"Pattern at index {index} must be a dictionary."
                )

            pattern = item.get("pattern")
            replacement = item.get("replacement")

            if not isinstance(pattern, str) or not pattern:
                raise ValueError(
                    f"Pattern at index {index} must be a non-empty string."
                )

            if len(pattern) > MAX_PATTERN_LENGTH:
                raise ValueError(
                    f"Pattern at index {index} is too long."
                )

            if not isinstance(replacement, str):
                raise TypeError(
                    f"Replacement at index {index} must be a string."
                )

            if len(replacement) > MAX_REPLACEMENT_LENGTH:
                raise ValueError(
                    f"Replacement at index {index} is too long."
                )

            normalised.append((pattern, replacement))

        return normalised

    def _compile_patterns(self) -> list[tuple[re.Pattern[str], str]]:
        """Compile configured patterns."""
        compiled: list[tuple[re.Pattern[str], str]] = []

        for pattern, replacement in self.patterns:
            expression = pattern

            if not self.use_regex:
                expression = re.escape(expression)

            if self.whole_word and not self.use_regex:
                expression = (
                    r"(?<!\w)"
                    + expression
                    + r"(?!\w)"
                )

            flags = 0 if self.case_sensitive else re.IGNORECASE

            try:
                compiled.append(
                    (re.compile(expression, flags), replacement)
                )

            except re.error as exc:
                raise ValueError(
                    f"Invalid regular expression '{pattern}': {exc}"
                ) from exc

        return compiled

    def _replace_content(self, content: str) -> tuple[str, int]:
        """Apply all configured replacements in sequence."""
        total_replacements = 0
        result = content

        for expression, replacement in self._compiled_patterns:
            remaining = (
                self.maximum_replacements - total_replacements
                if self.maximum_replacements
                else 0
            )

            if self.maximum_replacements and remaining <= 0:
                break

            result, count = expression.subn(
                replacement,
                result,
                count=remaining,
            )

            total_replacements += count

        return result, total_replacements

    async def transform(
        self,
        transformation_input: TransformationInput,
    ) -> TransformationOutput:
        """Execute configured replacements."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                transformation_input,
                reason="Replacement transformation is disabled.",
            )

        try:
            text = transformation_input.text
            caption = transformation_input.caption

            text_replacements = 0
            caption_replacements = 0

            if self.apply_to_text:
                text, text_replacements = self._replace_content(text)

            if self.apply_to_caption:
                caption, caption_replacements = self._replace_content(
                    caption
                )

            total_replacements = (
                text_replacements + caption_replacements
            )

            return self.build_result(
                transformation_input,
                text=text,
                caption=caption,
                metadata={
                    "pattern_count": len(self.patterns),
                    "text_replacements": text_replacements,
                    "caption_replacements": caption_replacements,
                    "total_replacements": total_replacements,
                    "regex_enabled": self.use_regex,
                    "case_sensitive": self.case_sensitive,
                },
                started_at=started_at,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Text replacement transformation failed",
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
