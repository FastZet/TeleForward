"""
TeleForward keyword filtering utilities.

Supports keyword, phrase and regular-expression matching against
Telegram message content.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


MAX_TEXT_LENGTH = 100_000
MAX_KEYWORDS = 1_000
MAX_KEYWORD_LENGTH = 512


@dataclass(frozen=True, slots=True)
class KeywordFilterConfig:
    """Configuration for keyword filtering."""

    required_keywords: tuple[str, ...] = ()
    allowed_keywords: tuple[str, ...] = ()
    blocked_keywords: tuple[str, ...] = ()

    case_sensitive: bool = False
    whole_word: bool = False
    require_all: bool = True

    use_regex: bool = False
    normalise_unicode: bool = True


@dataclass(frozen=True, slots=True)
class KeywordFilterResult:
    """Result of keyword filtering."""

    matched: bool
    matched_keywords: tuple[str, ...]
    missing_keywords: tuple[str, ...] = ()
    blocked_keywords: tuple[str, ...] = ()
    rejected_keywords: tuple[str, ...] = ()
    reason: str | None = None


class KeywordFilter:
    """Evaluate message text against keyword filtering rules."""

    @staticmethod
    def _validate_keywords(
        keywords: tuple[str, ...],
        field_name: str,
    ) -> tuple[str, ...]:
        if not isinstance(keywords, (tuple, list)):
            raise TypeError(
                f"{field_name} must be a tuple or list of strings."
            )

        if len(keywords) > MAX_KEYWORDS:
            raise ValueError(
                f"{field_name} exceeds the maximum keyword count."
            )

        validated: list[str] = []

        for keyword in keywords:
            if not isinstance(keyword, str):
                raise TypeError(
                    f"Every item in {field_name} must be a string."
                )

            keyword = keyword.strip()

            if not keyword:
                raise ValueError(
                    f"{field_name} cannot contain empty keywords."
                )

            if len(keyword) > MAX_KEYWORD_LENGTH:
                raise ValueError(
                    f"A keyword in {field_name} is too long."
                )

            validated.append(keyword)

        return tuple(validated)

    @staticmethod
    def _prepare_text(
        text: str | None,
        *,
        normalise_unicode: bool,
    ) -> str:
        if text is None:
            return ""

        if not isinstance(text, str):
            raise TypeError("Message text must be a string.")

        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Message text exceeds the maximum length.")

        if normalise_unicode:
            return unicodedata.normalize("NFC", text)

        return text

    @staticmethod
    def _prepare_keyword(
        keyword: str,
        *,
        normalise_unicode: bool,
    ) -> str:
        if normalise_unicode:
            return unicodedata.normalize("NFC", keyword)

        return keyword

    def _contains(
        self,
        text: str,
        keyword: str,
        *,
        case_sensitive: bool,
        whole_word: bool,
        use_regex: bool,
    ) -> bool:
        """Check whether a keyword or pattern occurs in the text."""
        flags = 0 if case_sensitive else re.IGNORECASE

        if use_regex:
            pattern = keyword
        elif whole_word:
            pattern = (
                r"(?<!\w)"
                + re.escape(keyword)
                + r"(?!\w)"
            )
        else:
            return (
                keyword in text
                if case_sensitive
                else keyword.casefold() in text.casefold()
            )

        try:
            return re.search(pattern, text, flags) is not None
        except re.error as exc:
            raise ValueError(
                f"Invalid keyword regular expression: {keyword!r}"
            ) from exc

    def matches(
        self,
        text: str | None,
        config: KeywordFilterConfig,
    ) -> KeywordFilterResult:
        """Evaluate message text against keyword constraints."""
        for field_name in (
            "case_sensitive",
            "whole_word",
            "require_all",
            "use_regex",
            "normalise_unicode",
        ):
            if not isinstance(getattr(config, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean.")

        required = self._validate_keywords(
            config.required_keywords,
            "required_keywords",
        )

        allowed = self._validate_keywords(
            config.allowed_keywords,
            "allowed_keywords",
        )

        blocked = self._validate_keywords(
            config.blocked_keywords,
            "blocked_keywords",
        )

        content = self._prepare_text(
            text,
            normalise_unicode=config.normalise_unicode,
        )

        def find_matches(
            keywords: tuple[str, ...],
        ) -> tuple[str, ...]:
            matched: list[str] = []

            for keyword in keywords:
                prepared_keyword = self._prepare_keyword(
                    keyword,
                    normalise_unicode=config.normalise_unicode,
                )

                if self._contains(
                    content,
                    prepared_keyword,
                    case_sensitive=config.case_sensitive,
                    whole_word=config.whole_word,
                    use_regex=config.use_regex,
                ):
                    matched.append(keyword)

            return tuple(matched)

        matched_required = find_matches(required)
        matched_allowed = find_matches(allowed)
        matched_blocked = find_matches(blocked)

        missing = tuple(
            keyword
            for keyword in required
            if keyword not in matched_required
        )

        if config.require_all:
            required_matched = not missing
        else:
            required_matched = (
                not required or bool(matched_required)
            )

        allowed_matched = (
            not allowed or bool(matched_allowed)
        )

        matched = (
            required_matched
            and allowed_matched
            and not matched_blocked
        )

        if matched_blocked:
            reason = "Message contains blocked keywords."
        elif missing and config.require_all:
            reason = "One or more required keywords are missing."
        elif not required_matched:
            reason = "None of the required keywords were found."
        elif not allowed_matched:
            reason = "No allowed keyword was found."
        else:
            reason = "All keyword constraints are satisfied."

        return KeywordFilterResult(
            matched=matched,
            matched_keywords=tuple(
                dict.fromkeys(
                    matched_required + matched_allowed
                )
            ),
            missing_keywords=missing,
            blocked_keywords=matched_blocked,
            rejected_keywords=(),
            reason=reason,
        )
