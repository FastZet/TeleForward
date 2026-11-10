"""
TeleForward hashtag filtering utilities.

Extracts hashtags from message text and evaluates them against
configurable inclusion, exclusion and occurrence-count rules.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass


MAX_TEXT_LENGTH = 100_000
MAX_HASHTAGS = 2_000
MAX_HASHTAG_LENGTH = 100

HASHTAG_PATTERN = re.compile(
    r"(?<![\w/])#([\w]+)",
    re.UNICODE,
)


@dataclass(frozen=True, slots=True)
class HashtagFilterConfig:
    """Configuration for hashtag filtering."""

    required_hashtags: frozenset[str] = frozenset()
    allowed_hashtags: frozenset[str] = frozenset()
    blocked_hashtags: frozenset[str] = frozenset()

    min_hashtags: int | None = None
    max_hashtags: int | None = None

    case_sensitive: bool = False
    require_all: bool = True
    match_exact: bool = True


@dataclass(frozen=True, slots=True)
class HashtagFilterResult:
    """Result of hashtag extraction and filtering."""

    matched: bool
    hashtags: tuple[str, ...]
    counts: dict[str, int]
    missing_required: tuple[str, ...] = ()
    blocked_matches: tuple[str, ...] = ()
    rejected_matches: tuple[str, ...] = ()
    reason: str | None = None


class HashtagFilter:
    """Extract and evaluate hashtags in Telegram message text."""

    @staticmethod
    def _normalise(
        hashtag: str,
        *,
        case_sensitive: bool,
    ) -> str:
        """Normalise a hashtag without its leading hash."""
        if not isinstance(hashtag, str):
            raise TypeError("Hashtags must be strings.")

        value = hashtag.strip()

        if value.startswith("#"):
            value = value[1:]

        value = unicodedata.normalize("NFC", value)

        if (
            not value
            or len(value) > MAX_HASHTAG_LENGTH
            or not all(
                character.isalnum() or character == "_"
                for character in value
            )
        ):
            raise ValueError(f"Invalid hashtag: {hashtag!r}")

        return value if case_sensitive else value.casefold()

    def extract(
        self,
        text: str | None,
        *,
        case_sensitive: bool = False,
        unique: bool = False,
    ) -> tuple[str, ...]:
        """Extract hashtags from message text."""
        if text is None:
            return ()

        if not isinstance(text, str):
            raise TypeError("Message text must be a string.")

        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Message text exceeds the maximum length.")

        results: list[str] = []
        seen: set[str] = set()

        for match in HASHTAG_PATTERN.finditer(text):
            hashtag = self._normalise(
                match.group(1),
                case_sensitive=case_sensitive,
            )

            if unique:
                if hashtag in seen:
                    continue
                seen.add(hashtag)

            results.append(hashtag)

            if len(results) > MAX_HASHTAGS:
                raise ValueError("Message contains too many hashtags.")

        return tuple(results)

    def _normalise_set(
        self,
        values: frozenset[str],
        *,
        case_sensitive: bool,
    ) -> frozenset[str]:
        """Validate and normalise configured hashtag collections."""
        if not isinstance(values, (set, frozenset)):
            raise TypeError("Hashtag collections must be sets.")

        return frozenset(
            self._normalise(
                value,
                case_sensitive=case_sensitive,
            )
            for value in values
        )

    @staticmethod
    def _validate_count(
        value: int | None,
        field_name: str,
    ) -> None:
        if value is None:
            return

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > MAX_HASHTAGS
        ):
            raise ValueError(
                f"{field_name} must be between 0 and {MAX_HASHTAGS}."
            )

    def matches(
        self,
        text: str | None,
        config: HashtagFilterConfig,
    ) -> HashtagFilterResult:
        """Evaluate message hashtags against the supplied configuration."""
        self._validate_count(config.min_hashtags, "min_hashtags")
        self._validate_count(config.max_hashtags, "max_hashtags")

        if (
            config.min_hashtags is not None
            and config.max_hashtags is not None
            and config.min_hashtags > config.max_hashtags
        ):
            raise ValueError(
                "min_hashtags cannot exceed max_hashtags."
            )

        for field_name in (
            "case_sensitive",
            "require_all",
            "match_exact",
        ):
            if not isinstance(getattr(config, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean.")

        hashtags = self.extract(
            text,
            case_sensitive=config.case_sensitive,
        )

        counts = Counter(hashtags)
        found = frozenset(counts)

        required = self._normalise_set(
            config.required_hashtags,
            case_sensitive=config.case_sensitive,
        )

        allowed = self._normalise_set(
            config.allowed_hashtags,
            case_sensitive=config.case_sensitive,
        )

        blocked = self._normalise_set(
            config.blocked_hashtags,
            case_sensitive=config.case_sensitive,
        )

        missing_required = required - found

        if config.require_all:
            required_matched = not missing_required
        else:
            required_matched = (
                not required or bool(required & found)
            )

        if config.match_exact:
            blocked_matches = blocked & found
            rejected_matches = (
                found - allowed
                if allowed
                else frozenset()
            )
        else:
            blocked_matches = frozenset(
                hashtag
                for hashtag in found
                if any(
                    blocked_tag in hashtag
                    for blocked_tag in blocked
                )
            )

            rejected_matches = frozenset(
                hashtag
                for hashtag in found
                if allowed
                and not any(
                    allowed_tag in hashtag
                    for allowed_tag in allowed
                )
            )

        count_matched = (
            config.min_hashtags is None
            or len(hashtags) >= config.min_hashtags
        ) and (
            config.max_hashtags is None
            or len(hashtags) <= config.max_hashtags
        )

        matched = (
            required_matched
            and not blocked_matches
            and not rejected_matches
            and count_matched
        )

        if blocked_matches:
            reason = "Message contains blocked hashtags."
        elif rejected_matches:
            reason = "Message contains hashtags outside the allowlist."
        elif not required_matched:
            reason = "Required hashtags are missing."
        elif not count_matched:
            reason = "Hashtag count is outside the configured range."
        else:
            reason = "All hashtag constraints are satisfied."

        return HashtagFilterResult(
            matched=matched,
            hashtags=hashtags,
            counts=dict(counts),
            missing_required=tuple(sorted(missing_required)),
            blocked_matches=tuple(sorted(blocked_matches)),
            rejected_matches=tuple(sorted(rejected_matches)),
            reason=reason,
        )
