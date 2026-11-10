"""
TeleForward language filtering utilities.

Provides language detection result handling and configurable language
allowlist and blocklist evaluation.

Language detection itself is delegated to an optional external provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


MAX_TEXT_LENGTH = 100_000
MAX_LANGUAGE_CODE_LENGTH = 35


class LanguageMatchMode(StrEnum):
    ALLOWLIST = "allowlist"
    BLOCKLIST = "blocklist"


@dataclass(frozen=True, slots=True)
class LanguageDetection:
    """Result returned by a language detection provider."""

    language_code: str
    confidence: float
    provider: str
    is_reliable: bool = True


@dataclass(frozen=True, slots=True)
class LanguageFilterConfig:
    """Configuration for language filtering."""

    allowed_languages: frozenset[str] = frozenset()
    blocked_languages: frozenset[str] = frozenset()

    minimum_confidence: float = 0.70
    require_reliable_detection: bool = True

    allow_unknown_language: bool = False
    allow_empty_text: bool = False


@dataclass(frozen=True, slots=True)
class LanguageFilterResult:
    """Result of language filtering."""

    matched: bool
    detection: LanguageDetection | None
    reason: str


class LanguageDetector(Protocol):
    """Interface implemented by language detection providers."""

    async def detect(
        self,
        text: str,
    ) -> LanguageDetection:
        """Detect the language of the supplied text."""
        ...


class LanguageFilter:
    """Evaluate language detection results against filtering rules."""

    LANGUAGE_CODE_PATTERN = re.compile(
        r"^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*$"
    )

    @classmethod
    def normalise_language_code(cls, value: str) -> str:
        """
        Normalise a BCP 47-style language tag.

        This performs syntactic validation and basic case normalisation.
        It does not verify that a language or region subtag is registered.
        """
        if not isinstance(value, str):
            raise TypeError("Language code must be a string.")

        value = value.strip()

        if (
            not value
            or len(value) > MAX_LANGUAGE_CODE_LENGTH
            or not cls.LANGUAGE_CODE_PATTERN.fullmatch(value)
        ):
            raise ValueError(f"Invalid language code: {value!r}")

        parts = value.split("-")
        normalised = [parts[0].lower()]

        for part in parts[1:]:
            if len(part) == 4 and part.isalpha():
                normalised.append(part.title())
            elif (
                len(part) == 2 and part.isalpha()
            ) or (
                len(part) == 3 and part.isdigit()
            ):
                normalised.append(part.upper())
            else:
                normalised.append(part.lower())

        return "-".join(normalised)

    @classmethod
    def _normalise_language_set(
        cls,
        values: frozenset[str],
        field_name: str,
    ) -> frozenset[str]:
        if not isinstance(values, (set, frozenset)):
            raise TypeError(f"{field_name} must be a set.")

        return frozenset(
            cls.normalise_language_code(value)
            for value in values
        )

    @staticmethod
    def _validate_detection(
        detection: LanguageDetection,
    ) -> None:
        if not isinstance(detection, LanguageDetection):
            raise TypeError(
                "detection must be a LanguageDetection instance."
            )

        if not isinstance(detection.confidence, (int, float)):
            raise ValueError("Detection confidence must be numeric.")

        if isinstance(detection.confidence, bool):
            raise ValueError("Detection confidence must be numeric.")

        if not 0.0 <= detection.confidence <= 1.0:
            raise ValueError(
                "Detection confidence must be between 0 and 1."
            )

        if not isinstance(detection.provider, str) or not (
            detection.provider.strip()
        ):
            raise ValueError("Detection provider cannot be empty.")

        if not isinstance(detection.is_reliable, bool):
            raise ValueError("is_reliable must be a boolean.")

        LanguageFilter.normalise_language_code(
            detection.language_code
        )

    @staticmethod
    def _validate_config(
        config: LanguageFilterConfig,
    ) -> None:
        for field_name in (
            "require_reliable_detection",
            "allow_unknown_language",
            "allow_empty_text",
        ):
            if not isinstance(getattr(config, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean.")

        if (
            isinstance(config.minimum_confidence, bool)
            or not isinstance(config.minimum_confidence, (int, float))
            or not 0.0 <= config.minimum_confidence <= 1.0
        ):
            raise ValueError(
                "minimum_confidence must be between 0 and 1."
            )

    def matches(
        self,
        detection: LanguageDetection | None,
        config: LanguageFilterConfig,
    ) -> LanguageFilterResult:
        """Evaluate a language detection result."""
        self._validate_config(config)

        allowed = self._normalise_language_set(
            config.allowed_languages,
            "allowed_languages",
        )

        blocked = self._normalise_language_set(
            config.blocked_languages,
            "blocked_languages",
        )

        if allowed & blocked:
            raise ValueError(
                "A language cannot appear in both allowlist and blocklist."
            )

        if detection is None:
            matched = config.allow_unknown_language

            return LanguageFilterResult(
                matched=matched,
                detection=None,
                reason=(
                    "Unknown language is permitted."
                    if matched
                    else "Language could not be detected."
                ),
            )

        self._validate_detection(detection)

        language = self.normalise_language_code(
            detection.language_code
        )

        base_language = language.split("-", 1)[0]

        if (
            config.require_reliable_detection
            and not detection.is_reliable
        ):
            return LanguageFilterResult(
                matched=False,
                detection=detection,
                reason="Language detection was marked unreliable.",
            )

        if detection.confidence < config.minimum_confidence:
            return LanguageFilterResult(
                matched=False,
                detection=detection,
                reason="Language detection confidence is below threshold.",
            )

        if language in blocked or base_language in blocked:
            return LanguageFilterResult(
                matched=False,
                detection=detection,
                reason="Detected language is blocked.",
            )

        if allowed and not (
            language in allowed or base_language in allowed
        ):
            return LanguageFilterResult(
                matched=False,
                detection=detection,
                reason="Detected language is not in the allowlist.",
            )

        return LanguageFilterResult(
            matched=True,
            detection=detection,
            reason="Detected language satisfies the configured rules.",
        )

    async def evaluate(
        self,
        text: str | None,
        config: LanguageFilterConfig,
        detector: LanguageDetector,
    ) -> LanguageFilterResult:
        """
        Detect message language and evaluate the configured rules.

        Detection is performed asynchronously through the supplied provider.
        """
        self._validate_config(config)

        if text is None or not text.strip():
            matched = config.allow_empty_text

            return LanguageFilterResult(
                matched=matched,
                detection=None,
                reason=(
                    "Empty message content is permitted."
                    if matched
                    else "Message contains no text to analyse."
                ),
            )

        if not isinstance(text, str):
            raise TypeError("Message text must be a string.")

        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Message text exceeds the maximum length.")

        detection = await detector.detect(text)

        return self.matches(detection, config)
