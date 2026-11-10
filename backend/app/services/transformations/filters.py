"""
TeleForward content filtering transformation.

Supports line-level inclusion and exclusion using literal phrases
or regular expressions.
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

MAX_FILTER_PATTERNS = 100
MAX_PATTERN_LENGTH = 512
MAX_CONTENT_LENGTH = 100_000


class FiltersTransformation(BaseTransformation):
    """Filter message content according to configurable line rules."""

    name = "filters"
    version = "1.0.0"

    def __init__(
        self,
        *,
        remove_lines_containing: list[str] | None = None,
        keep_lines_containing: list[str] | None = None,
        remove_patterns: list[str] | None = None,
        keep_patterns: list[str] | None = None,
        case_sensitive: bool = False,
        regex_enabled: bool = False,
        remove_empty_lines: bool = False,
        preserve_line_endings: bool = True,
        match_all: bool = False,
        apply_to_text: bool = True,
        apply_to_caption: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)

        boolean_options = {
            "case_sensitive": case_sensitive,
            "regex_enabled": regex_enabled,
            "remove_empty_lines": remove_empty_lines,
            "preserve_line_endings": preserve_line_endings,
            "match_all": match_all,
            "apply_to_text": apply_to_text,
            "apply_to_caption": apply_to_caption,
        }

        for name, value in boolean_options.items():
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean.")

        self.remove_lines_containing = self._validate_patterns(
            remove_lines_containing or []
        )
        self.keep_lines_containing = self._validate_patterns(
            keep_lines_containing or []
        )
        self.remove_patterns = self._validate_patterns(
            remove_patterns or []
        )
        self.keep_patterns = self._validate_patterns(
            keep_patterns or []
        )

        self.case_sensitive = case_sensitive
        self.regex_enabled = regex_enabled
        self.remove_empty_lines = remove_empty_lines
        self.preserve_line_endings = preserve_line_endings
        self.match_all = match_all
        self.apply_to_text = apply_to_text
        self.apply_to_caption = apply_to_caption

        self._compiled_remove_patterns = self._compile_patterns(
            self.remove_patterns
        )
        self._compiled_keep_patterns = self._compile_patterns(
            self.keep_patterns
        )

    @staticmethod
    def _validate_patterns(patterns: list[str]) -> tuple[str, ...]:
        if not isinstance(patterns, list):
            raise TypeError("Filter patterns must be supplied as lists.")

        if len(patterns) > MAX_FILTER_PATTERNS:
            raise ValueError(
                f"At most {MAX_FILTER_PATTERNS} patterns are allowed."
            )

        result: list[str] = []

        for pattern in patterns:
            if not isinstance(pattern, str):
                raise TypeError("Every filter pattern must be a string.")

            if not pattern:
                raise ValueError("Filter patterns cannot be empty.")

            if len(pattern) > MAX_PATTERN_LENGTH:
                raise ValueError(
                    f"Filter patterns cannot exceed "
                    f"{MAX_PATTERN_LENGTH} characters."
                )

            result.append(pattern)

        return tuple(result)

    def _compile_patterns(
        self,
        patterns: tuple[str, ...],
    ) -> tuple[re.Pattern[str], ...]:
        """Compile configured patterns when regex mode is enabled."""

        if not self.regex_enabled:
            return ()

        flags = 0 if self.case_sensitive else re.IGNORECASE

        try:
            return tuple(
                re.compile(pattern, flags)
                for pattern in patterns
            )
        except re.error as exc:
            raise ValueError(
                f"Invalid regular expression: {exc}"
            ) from exc

    def _matches(
        self,
        line: str,
        literal_patterns: tuple[str, ...],
        compiled_patterns: tuple[re.Pattern[str], ...],
    ) -> bool:
        """Determine whether a line matches configured patterns."""

        matches: list[bool] = []

        if self.regex_enabled:
            matches.extend(
                pattern.search(line) is not None
                for pattern in compiled_patterns
            )
        else:
            candidate = line if self.case_sensitive else line.casefold()

            matches.extend(
                (
                    pattern if self.case_sensitive else pattern.casefold()
                ) in candidate
                for pattern in literal_patterns
            )

        if not matches:
            return False

        return all(matches) if self.match_all else any(matches)

    def _transform_content(
        self,
        content: str,
    ) -> tuple[str, int, int]:
        """Apply line filtering and return content and removal counts."""

        if not content:
            return content, 0, 0

        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content exceeds the {MAX_CONTENT_LENGTH}-character limit."
            )

        if not any((
            self.remove_lines_containing,
            self.keep_lines_containing,
            self.remove_patterns,
            self.keep_patterns,
            self.remove_empty_lines,
        )):
            return content, 0, 0

        lines = content.splitlines(keepends=self.preserve_line_endings)

        if len(lines) > MAX_CONTENT_LENGTH:
            raise ValueError("Content contains too many lines.")

        retained: list[str] = []
        removed_count = 0
        empty_removed_count = 0

        for line in lines:
            content_line = line.rstrip("\r\n")

            if self.remove_empty_lines and not content_line.strip():
                removed_count += 1
                empty_removed_count += 1
                continue

            remove_match = (
                self._matches(
                    content_line,
                    self.remove_lines_containing,
                    self._compiled_remove_patterns,
                )
                or self._matches(
                    content_line,
                    self.remove_patterns,
                    self._compiled_remove_patterns,
                )
            )

            if remove_match:
                removed_count += 1
                continue

            if self.keep_lines_containing or self.keep_patterns:
                keep_match = (
                    self._matches(
                        content_line,
                        self.keep_lines_containing,
                        self._compiled_keep_patterns,
                    )
                    or self._matches(
                        content_line,
                        self.keep_patterns,
                        self._compiled_keep_patterns,
                    )
                )

                if not keep_match:
                    removed_count += 1
                    continue

            retained.append(line)

        return "".join(retained), removed_count, empty_removed_count

    async def transform(
        self,
        transformation_input: TransformationInput,
    ) -> TransformationOutput:
        """Filter lines in message text and captions."""

        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                transformation_input,
                reason="Content filtering transformation is disabled.",
            )

        try:
            text = transformation_input.text
            caption = transformation_input.caption

            text_removed = 0
            caption_removed = 0
            empty_lines_removed = 0

            if self.apply_to_text:
                text, text_removed, text_empty = (
                    self._transform_content(text)
                )
                empty_lines_removed += text_empty

            if self.apply_to_caption:
                caption, caption_removed, caption_empty = (
                    self._transform_content(caption)
                )
                empty_lines_removed += caption_empty

            return self.build_result(
                transformation_input,
                text=text,
                caption=caption,
                metadata={
                    "text_lines_removed": text_removed,
                    "caption_lines_removed": caption_removed,
                    "total_lines_removed": (
                        text_removed + caption_removed
                    ),
                    "empty_lines_removed": empty_lines_removed,
                    "regex_enabled": self.regex_enabled,
                    "case_sensitive": self.case_sensitive,
                },
                started_at=started_at,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Content filtering transformation failed",
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
