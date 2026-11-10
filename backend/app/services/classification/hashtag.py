"""
TeleForward hashtag classifier.

Extracts and analyses hashtags from Telegram message text and captions.
Supports allowlists, blocklists and configurable case sensitivity.
"""

from __future__ import annotations

import logging
import re
import time

from collections import Counter

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)


logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 100_000
MAX_HASHTAGS = 1_000
MAX_HASHTAG_LENGTH = 128

HASHTAG_PATTERN = re.compile(
    r"(?<!\w)#(?P<hashtag>[\w]{1,128})",
    re.UNICODE,
)


class HashtagClassifier(BaseClassifier):
    """Extract and classify hashtags in Telegram messages."""

    name = "hashtag"
    version = "1.0.0"

    def __init__(
        self,
        *,
        allowed_hashtags: set[str] | frozenset[str] | None = None,
        blocked_hashtags: set[str] | frozenset[str] | None = None,
        case_sensitive: bool = False,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        if not isinstance(case_sensitive, bool):
            raise ValueError("case_sensitive must be a boolean.")

        self.case_sensitive = case_sensitive

        self.allowed_hashtags = self._validate_hashtags(
            allowed_hashtags,
            "allowed_hashtags",
        )

        self.blocked_hashtags = self._validate_hashtags(
            blocked_hashtags,
            "blocked_hashtags",
        )

        if (
            self.allowed_hashtags is not None
            and self.blocked_hashtags is not None
        ):
            overlap = (
                self.allowed_hashtags
                & self.blocked_hashtags
            )

            if overlap:
                raise ValueError(
                    "A hashtag cannot be both allowed and blocked: "
                    + ", ".join(sorted(overlap))
                )

    def _validate_hashtags(
        self,
        hashtags: set[str] | frozenset[str] | None,
        parameter_name: str,
    ) -> frozenset[str] | None:
        """Validate and normalise hashtag configuration."""
        if hashtags is None:
            return None

        if not isinstance(hashtags, (set, frozenset)):
            raise TypeError(
                f"{parameter_name} must be a set or frozenset."
            )

        if len(hashtags) > MAX_HASHTAGS:
            raise ValueError(
                f"{parameter_name} cannot contain more than "
                f"{MAX_HASHTAGS} entries."
            )

        validated: set[str] = set()

        for hashtag in hashtags:
            if not isinstance(hashtag, str):
                raise TypeError("Hashtags must be strings.")

            normalised = hashtag.strip().lstrip("#")

            if not normalised:
                raise ValueError("Hashtags cannot be empty.")

            if len(normalised) > MAX_HASHTAG_LENGTH:
                raise ValueError(
                    "Hashtags cannot exceed "
                    f"{MAX_HASHTAG_LENGTH} characters."
                )

            if self.case_sensitive:
                validated.add(normalised)
            else:
                validated.add(normalised.casefold())

        return frozenset(validated)

    @staticmethod
    def _extract_content(
        classification_input: ClassificationInput,
    ) -> str:
        """Combine message text and caption."""
        content = "\n".join(
            value
            for value in (
                classification_input.text,
                classification_input.caption,
            )
            if isinstance(value, str) and value
        )

        return content[:MAX_CONTENT_LENGTH]

    def _normalise(
        self,
        hashtag: str,
    ) -> str:
        """Apply configured case normalisation."""
        return hashtag if self.case_sensitive else hashtag.casefold()

    def _extract_hashtags(
        self,
        content: str,
    ) -> Counter[str]:
        """Extract hashtags and count their occurrences."""
        counts: Counter[str] = Counter()

        for match in HASHTAG_PATTERN.finditer(content):
            hashtag = self._normalise(
                match.group("hashtag")
            )

            counts[hashtag] += 1

            if sum(counts.values()) >= MAX_HASHTAGS:
                break

        return counts

    def _filter_hashtags(
        self,
        hashtags: Counter[str],
    ) -> Counter[str]:
        """Apply configured allowlist and blocklist."""
        filtered: Counter[str] = Counter()

        for hashtag, count in hashtags.items():
            if (
                self.allowed_hashtags is not None
                and hashtag not in self.allowed_hashtags
            ):
                continue

            if (
                self.blocked_hashtags is not None
                and hashtag in self.blocked_hashtags
            ):
                continue

            filtered[hashtag] = count

        return filtered

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Extract and classify message hashtags."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Hashtag classifier is disabled.",
            )

        try:
            content = self._extract_content(
                classification_input
            )

            if not content.strip():
                return self.skipped_result(
                    classifier=self.name,
                    reason="Message contains no searchable text.",
                )

            extracted = self._extract_hashtags(content)
            filtered = self._filter_hashtags(extracted)

            labels = tuple(
                ClassificationLabel(
                    name=hashtag,
                    category="hashtag",
                    confidence=1.0,
                )
                for hashtag in sorted(
                    filtered,
                    key=lambda item: (
                        -filtered[item],
                        item,
                    ),
                )
            )

            labels = self.filter_by_confidence(labels)

            primary_label = (
                max(
                    labels,
                    key=lambda label: (
                        filtered[label.name],
                        label.confidence,
                        label.name,
                    ),
                )
                if labels
                else None
            )

            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            return ClassificationResult(
                classifier=self.name,
                status=ClassificationStatus.COMPLETED,
                labels=labels,
                primary_label=primary_label,
                confidence=(
                    primary_label.confidence
                    if primary_label
                    else 0.0
                ),
                processing_time_ms=elapsed_ms,
                metadata={
                    "hashtags": [
                        {
                            "name": hashtag,
                            "count": count,
                        }
                        for hashtag, count in filtered.most_common()
                    ],
                    "unique_hashtag_count": len(filtered),
                    "total_occurrences": sum(filtered.values()),
                    "excluded_hashtag_count": (
                        len(extracted) - len(filtered)
                    ),
                    "case_sensitive": self.case_sensitive,
                },
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Hashtag classification failed",
                extra={
                    "message_id": classification_input.message_id,
                    "classifier": self.name,
                },
            )

            return ClassificationResult(
                classifier=self.name,
                status=ClassificationStatus.FAILED,
                labels=(),
                primary_label=None,
                confidence=0.0,
                processing_time_ms=elapsed_ms,
                error=str(exc)[:2000],
                metadata={
                    "error_type": type(exc).__name__,
                },
            )
