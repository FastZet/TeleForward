"""
TeleForward keyword classifier.

Classifies Telegram messages by matching configured keywords against
message text and captions.
"""

from __future__ import annotations

import logging
import re
import time

from collections.abc import Mapping, Sequence

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)


logger = logging.getLogger(__name__)

MAX_CATEGORIES = 100
MAX_KEYWORDS_PER_CATEGORY = 200
MAX_TOTAL_KEYWORDS = 2_000
MAX_KEYWORD_LENGTH = 128


class KeywordClassifier(BaseClassifier):
    """Classify messages using configurable keyword categories."""

    name = "keyword"
    version = "1.0.0"

    def __init__(
        self,
        categories: Mapping[str, Sequence[str]],
        *,
        case_sensitive: bool = False,
        whole_word: bool = False,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        if not isinstance(categories, Mapping):
            raise TypeError("categories must be a mapping.")

        if len(categories) > MAX_CATEGORIES:
            raise ValueError(
                f"At most {MAX_CATEGORIES} categories are allowed."
            )

        if not isinstance(case_sensitive, bool):
            raise ValueError("case_sensitive must be a boolean.")

        if not isinstance(whole_word, bool):
            raise ValueError("whole_word must be a boolean.")

        self.case_sensitive = case_sensitive
        self.whole_word = whole_word
        self.categories = self._validate_categories(categories)

        self._compiled_patterns: dict[
            str,
            tuple[tuple[str, re.Pattern[str]], ...],
        ] = self._compile_patterns()

    @staticmethod
    def _validate_categories(
        categories: Mapping[str, Sequence[str]],
    ) -> dict[str, tuple[str, ...]]:
        validated: dict[str, tuple[str, ...]] = {}
        total_keywords = 0

        for category, keywords in categories.items():
            if not isinstance(category, str) or not category.strip():
                raise ValueError(
                    "Category names must be non-empty strings."
                )

            category_name = category.strip()

            if len(category_name) > 128:
                raise ValueError(
                    "Category names cannot exceed 128 characters."
                )

            if category_name in validated:
                raise ValueError(
                    f"Duplicate category: {category_name!r}."
                )

            if isinstance(keywords, (str, bytes)):
                raise TypeError(
                    f"Keywords for {category_name!r} must be a sequence, "
                    "not a string."
                )

            if not isinstance(keywords, Sequence):
                raise TypeError(
                    f"Keywords for {category_name!r} must be a sequence."
                )

            if len(keywords) > MAX_KEYWORDS_PER_CATEGORY:
                raise ValueError(
                    f"Category {category_name!r} exceeds the keyword limit."
                )

            normalised: list[str] = []

            for keyword in keywords:
                if not isinstance(keyword, str):
                    raise TypeError("Every keyword must be a string.")

                keyword = keyword.strip()

                if not keyword:
                    raise ValueError("Keywords cannot be empty.")

                if len(keyword) > MAX_KEYWORD_LENGTH:
                    raise ValueError(
                        f"Keywords cannot exceed {MAX_KEYWORD_LENGTH} "
                        "characters."
                    )

                if keyword not in normalised:
                    normalised.append(keyword)

            validated[category_name] = tuple(normalised)
            total_keywords += len(normalised)

        if total_keywords > MAX_TOTAL_KEYWORDS:
            raise ValueError(
                f"At most {MAX_TOTAL_KEYWORDS} total keywords are allowed."
            )

        return validated

    def _compile_patterns(
        self,
    ) -> dict[str, tuple[tuple[str, re.Pattern[str]], ...]]:
        """Compile keyword patterns once during initialisation."""
        flags = 0 if self.case_sensitive else re.IGNORECASE
        compiled: dict[
            str,
            tuple[tuple[str, re.Pattern[str]], ...],
        ] = {}

        for category, keywords in self.categories.items():
            patterns: list[tuple[str, re.Pattern[str]]] = []

            for keyword in keywords:
                expression = re.escape(keyword)

                if self.whole_word:
                    expression = (
                        rf"(?<!\w){expression}(?!\w)"
                    )

                patterns.append(
                    (
                        keyword,
                        re.compile(expression, flags),
                    )
                )

            compiled[category] = tuple(patterns)

        return compiled

    @staticmethod
    def _get_content(
        classification_input: ClassificationInput,
    ) -> str:
        """Combine message text and caption into searchable content."""
        parts = [
            classification_input.text,
            classification_input.caption,
        ]

        return "\n".join(
            part
            for part in parts
            if isinstance(part, str) and part
        )

    def _find_matches(
        self,
        content: str,
    ) -> dict[str, tuple[str, ...]]:
        """Find configured keywords grouped by category."""
        matches: dict[str, tuple[str, ...]] = {}

        for category, patterns in self._compiled_patterns.items():
            matched_keywords = tuple(
                keyword
                for keyword, pattern in patterns
                if pattern.search(content)
            )

            if matched_keywords:
                matches[category] = matched_keywords

        return matches

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Classify a message using configured keyword categories."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Keyword classifier is disabled.",
            )

        try:
            content = self._get_content(classification_input)

            if not content:
                return self.skipped_result(
                    classifier=self.name,
                    reason="Message contains no searchable text.",
                )

            matches = self._find_matches(content)

            labels = tuple(
                ClassificationLabel(
                    name=category,
                    category="keyword",
                    confidence=1.0,
                )
                for category in matches
            )

            labels = self.filter_by_confidence(labels)

            primary_label = (
                max(labels, key=lambda label: label.confidence)
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
                    "matched_keywords": {
                        category: list(keywords)
                        for category, keywords in matches.items()
                    },
                    "matched_categories": list(matches),
                    "case_sensitive": self.case_sensitive,
                    "whole_word": self.whole_word,
                },
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Keyword classification failed",
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
