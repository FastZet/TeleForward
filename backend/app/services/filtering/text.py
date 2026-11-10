"""
TeleForward text filtering utilities.

Provides reusable text matching operations for the filtering engine.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass


MAX_TEXT_LENGTH = 100_000
MAX_PATTERN_LENGTH = 512
MAX_KEYWORDS = 500


@dataclass(frozen=True, slots=True)
class TextMatchResult:
    """Result of a text-matching operation."""

    matched: bool
    matched_terms: tuple[str, ...] = ()
    unmatched_terms: tuple[str, ...] = ()
    reason: str | None = None


class TextFilter:
    """Perform text and keyword matching operations."""

    @staticmethod
    def normalise(
        text: str,
        *,
        case_sensitive: bool = False,
        unicode_normalisation: str = "NFKC",
    ) -> str:
        """Normalise text for consistent comparisons."""
        if not isinstance(text, str):
            raise TypeError("Text must be a string.")

        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Text exceeds the maximum allowed length.")

        try:
            text = unicodedata.normalize(
                unicode_normalisation,
                text,
            )
        except ValueError as exc:
            raise ValueError(
                "Unsupported Unicode normalisation form."
            ) from exc

        if not case_sensitive:
            text = text.casefold()

        return text

    @staticmethod
    def _validate_terms(
        terms: Iterable[str],
    ) -> tuple[str, ...]:
        """Validate and normalise a collection of terms."""
        if isinstance(terms, (str, bytes)):
            raise TypeError(
                "Terms must be an iterable of strings, not a string."
            )

        values = tuple(terms)

        if len(values) > MAX_KEYWORDS:
            raise ValueError("Too many terms supplied.")

        if any(
            not isinstance(term, str) or not term.strip()
            for term in values
        ):
            raise ValueError(
                "Every term must be a non-empty string."
            )

        return values

    def contains(
        self,
        text: str | None,
        phrase: str,
        *,
        case_sensitive: bool = False,
    ) -> bool:
        """Check whether text contains a phrase."""
        if text is None:
            return False

        if not isinstance(phrase, str) or not phrase:
            raise ValueError("Phrase must be a non-empty string.")

        normalised_text = self.normalise(
            text,
            case_sensitive=case_sensitive,
        )

        normalised_phrase = self.normalise(
            phrase,
            case_sensitive=case_sensitive,
        )

        return normalised_phrase in normalised_text

    def contains_any(
        self,
        text: str | None,
        terms: Iterable[str],
        *,
        case_sensitive: bool = False,
    ) -> TextMatchResult:
        """Check whether at least one term occurs in the text."""
        validated_terms = self._validate_terms(terms)

        if not validated_terms:
            return TextMatchResult(
                matched=False,
                reason="No search terms were supplied.",
            )

        if text is None:
            return TextMatchResult(
                matched=False,
                unmatched_terms=validated_terms,
                reason="Message contains no text.",
            )

        normalised_text = self.normalise(
            text,
            case_sensitive=case_sensitive,
        )

        matched = tuple(
            term
            for term in validated_terms
            if self.normalise(
                term,
                case_sensitive=case_sensitive,
            ) in normalised_text
        )

        unmatched = tuple(
            term
            for term in validated_terms
            if term not in matched
        )

        return TextMatchResult(
            matched=bool(matched),
            matched_terms=matched,
            unmatched_terms=unmatched,
        )

    def contains_all(
        self,
        text: str | None,
        terms: Iterable[str],
        *,
        case_sensitive: bool = False,
    ) -> TextMatchResult:
        """Check whether every supplied term occurs in the text."""
        validated_terms = self._validate_terms(terms)

        if not validated_terms:
            return TextMatchResult(
                matched=False,
                reason="No search terms were supplied.",
            )

        if text is None:
            return TextMatchResult(
                matched=False,
                unmatched_terms=validated_terms,
                reason="Message contains no text.",
            )

        normalised_text = self.normalise(
            text,
            case_sensitive=case_sensitive,
        )

        matched = tuple(
            term
            for term in validated_terms
            if self.normalise(
                term,
                case_sensitive=case_sensitive,
            ) in normalised_text
        )

        unmatched = tuple(
            term
            for term in validated_terms
            if term not in matched
        )

        return TextMatchResult(
            matched=len(matched) == len(validated_terms),
            matched_terms=matched,
            unmatched_terms=unmatched,
        )

    def matches_regex(
        self,
        text: str | None,
        pattern: str,
        *,
        case_sensitive: bool = False,
    ) -> bool:
        """Evaluate a regular expression against message text."""
        if text is None:
            return False

        if not isinstance(pattern, str) or not pattern:
            raise ValueError("Regex pattern must be a non-empty string.")

        if len(pattern) > MAX_PATTERN_LENGTH:
            raise ValueError("Regex pattern exceeds the maximum length.")

        normalised_text = self.normalise(
            text,
            case_sensitive=case_sensitive,
        )

        flags = 0 if case_sensitive else re.IGNORECASE

        compiled = re.compile(pattern, flags)

        return compiled.search(normalised_text) is not None

    def matches_any_regex(
        self,
        text: str | None,
        patterns: Iterable[str],
        *,
        case_sensitive: bool = False,
    ) -> TextMatchResult:
        """Check whether any regular-expression pattern matches."""
        validated_patterns = self._validate_terms(patterns)

        if not validated_patterns:
            return TextMatchResult(
                matched=False,
                reason="No regex patterns were supplied.",
            )

        matched: list[str] = []
        unmatched: list[str] = []

        for pattern in validated_patterns:
            if self.matches_regex(
                text,
                pattern,
                case_sensitive=case_sensitive,
            ):
                matched.append(pattern)
            else:
                unmatched.append(pattern)

        return TextMatchResult(
            matched=bool(matched),
            matched_terms=tuple(matched),
            unmatched_terms=tuple(unmatched),
        )

    def has_word(
        self,
        text: str | None,
        word: str,
        *,
        case_sensitive: bool = False,
    ) -> bool:
        """Check for a complete word rather than a substring."""
        if text is None:
            return False

        if not isinstance(word, str) or not word.strip():
            raise ValueError("Word must be a non-empty string.")

        normalised_text = self.normalise(
            text,
            case_sensitive=case_sensitive,
        )

        normalised_word = self.normalise(
            word.strip(),
            case_sensitive=case_sensitive,
        )

        pattern = (
            r"(?<!\w)"
            + re.escape(normalised_word)
            + r"(?!\w)"
        )

        return re.search(pattern, normalised_text) is not None

    def get_matching_lines(
        self,
        text: str | None,
        terms: Iterable[str],
        *,
        case_sensitive: bool = False,
    ) -> tuple[str, ...]:
        """Return lines containing at least one supplied term."""
        validated_terms = self._validate_terms(terms)

        if text is None or not validated_terms:
            return ()

        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Text exceeds the maximum allowed length.")

        normalised_terms = tuple(
            self.normalise(
                term,
                case_sensitive=case_sensitive,
            )
            for term in validated_terms
        )

        matching_lines: list[str] = []

        for line in text.splitlines():
            normalised_line = self.normalise(
                line,
                case_sensitive=case_sensitive,
            )

            if any(
                term in normalised_line
                for term in normalised_terms
            ):
                matching_lines.append(line)

        return tuple(matching_lines)
