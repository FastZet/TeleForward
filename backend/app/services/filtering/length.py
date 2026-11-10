"""
TeleForward message length filtering utilities.

Provides configurable length checks for Telegram message text and captions.
"""

from __future__ import annotations

from dataclasses import dataclass


MAX_MESSAGE_LENGTH = 100_000


@dataclass(frozen=True, slots=True)
class LengthFilterConfig:
    """Length constraints for message content."""

    min_characters: int | None = None
    max_characters: int | None = None

    min_words: int | None = None
    max_words: int | None = None

    min_lines: int | None = None
    max_lines: int | None = None

    min_caption_characters: int | None = None
    max_caption_characters: int | None = None

    strip_whitespace: bool = True
    count_unicode_codepoints: bool = True


@dataclass(frozen=True, slots=True)
class LengthMetrics:
    """Calculated message length metrics."""

    characters: int
    words: int
    lines: int
    caption_characters: int


@dataclass(frozen=True, slots=True)
class LengthFilterResult:
    """Result of message length evaluation."""

    matched: bool
    metrics: LengthMetrics
    failed_constraints: tuple[str, ...] = ()
    reason: str | None = None


class LengthFilter:
    """Evaluate message and caption lengths."""

    @staticmethod
    def _validate_limit(
        value: int | None,
        field_name: str,
    ) -> None:
        if value is None:
            return

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise ValueError(
                f"{field_name} must be a non-negative integer or None."
            )

        if value > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"{field_name} exceeds the maximum supported limit."
            )

    def validate_config(
        self,
        config: LengthFilterConfig,
    ) -> None:
        """Validate all configured length constraints."""
        limits = (
            ("min_characters", config.min_characters),
            ("max_characters", config.max_characters),
            ("min_words", config.min_words),
            ("max_words", config.max_words),
            ("min_lines", config.min_lines),
            ("max_lines", config.max_lines),
            (
                "min_caption_characters",
                config.min_caption_characters,
            ),
            (
                "max_caption_characters",
                config.max_caption_characters,
            ),
        )

        for field_name, value in limits:
            self._validate_limit(value, field_name)

        if (
            config.min_characters is not None
            and config.max_characters is not None
            and config.min_characters > config.max_characters
        ):
            raise ValueError(
                "min_characters cannot exceed max_characters."
            )

        if (
            config.min_words is not None
            and config.max_words is not None
            and config.min_words > config.max_words
        ):
            raise ValueError(
                "min_words cannot exceed max_words."
            )

        if (
            config.min_lines is not None
            and config.max_lines is not None
            and config.min_lines > config.max_lines
        ):
            raise ValueError(
                "min_lines cannot exceed max_lines."
            )

        if (
            config.min_caption_characters is not None
            and config.max_caption_characters is not None
            and config.min_caption_characters
            > config.max_caption_characters
        ):
            raise ValueError(
                "min_caption_characters cannot exceed "
                "max_caption_characters."
            )

        if not isinstance(config.strip_whitespace, bool):
            raise ValueError("strip_whitespace must be a boolean.")

        if not isinstance(config.count_unicode_codepoints, bool):
            raise ValueError(
                "count_unicode_codepoints must be a boolean."
            )

    @staticmethod
    def _prepare_text(
        text: str | None,
        *,
        strip_whitespace: bool,
    ) -> str:
        """Normalise optional message text."""
        if text is None:
            return ""

        if not isinstance(text, str):
            raise TypeError("Message content must be a string or None.")

        if len(text) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                "Message content exceeds the maximum supported length."
            )

        return text.strip() if strip_whitespace else text

    @staticmethod
    def _count_characters(
        text: str,
        *,
        count_unicode_codepoints: bool,
    ) -> int:
        """
        Count characters.

        Python's len() counts Unicode code points, not grapheme clusters.
        """
        if count_unicode_codepoints:
            return len(text)

        # Count UTF-8 bytes when codepoint counting is disabled.
        return len(text.encode("utf-8"))

    def calculate_metrics(
        self,
        text: str | None,
        caption: str | None = None,
        *,
        config: LengthFilterConfig | None = None,
    ) -> LengthMetrics:
        """Calculate message and caption length metrics."""
        config = config or LengthFilterConfig()

        message_text = self._prepare_text(
            text,
            strip_whitespace=config.strip_whitespace,
        )

        caption_text = self._prepare_text(
            caption,
            strip_whitespace=config.strip_whitespace,
        )

        return LengthMetrics(
            characters=self._count_characters(
                message_text,
                count_unicode_codepoints=config.count_unicode_codepoints,
            ),
            words=len(message_text.split()),
            lines=len(message_text.splitlines()),
            caption_characters=self._count_characters(
                caption_text,
                count_unicode_codepoints=config.count_unicode_codepoints,
            ),
        )

    def matches(
        self,
        text: str | None,
        config: LengthFilterConfig,
        *,
        caption: str | None = None,
    ) -> LengthFilterResult:
        """Evaluate a message against configured length constraints."""
        self.validate_config(config)

        metrics = self.calculate_metrics(
            text,
            caption,
            config=config,
        )

        failures: list[str] = []

        checks = (
            (
                "min_characters",
                metrics.characters,
                config.min_characters,
                "minimum",
            ),
            (
                "max_characters",
                metrics.characters,
                config.max_characters,
                "maximum",
            ),
            (
                "min_words",
                metrics.words,
                config.min_words,
                "minimum",
            ),
            (
                "max_words",
                metrics.words,
                config.max_words,
                "maximum",
            ),
            (
                "min_lines",
                metrics.lines,
                config.min_lines,
                "minimum",
            ),
            (
                "max_lines",
                metrics.lines,
                config.max_lines,
                "maximum",
            ),
            (
                "min_caption_characters",
                metrics.caption_characters,
                config.min_caption_characters,
                "minimum",
            ),
            (
                "max_caption_characters",
                metrics.caption_characters,
                config.max_caption_characters,
                "maximum",
            ),
        )

        for field_name, actual, expected, boundary in checks:
            if expected is None:
                continue

            if boundary == "minimum" and actual < expected:
                failures.append(field_name)

            elif boundary == "maximum" and actual > expected:
                failures.append(field_name)

        matched = not failures

        return LengthFilterResult(
            matched=matched,
            metrics=metrics,
            failed_constraints=tuple(failures),
            reason=(
                "Message satisfies all length constraints."
                if matched
                else "Message violates one or more length constraints."
            ),
        )
