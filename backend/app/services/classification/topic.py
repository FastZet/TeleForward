"""
TeleForward topic classifier.

Classifies messages into configurable topics using keyword-based
matching rules.
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

MAX_TOPICS = 100
MAX_TERMS_PER_TOPIC = 200
MAX_TOTAL_TERMS = 2_000
MAX_TERM_LENGTH = 128


class TopicClassifier(BaseClassifier):
    """Classify messages into configurable topics."""

    name = "topic"
    version = "1.0.0"

    def __init__(
        self,
        topics: Mapping[str, Sequence[str]],
        *,
        case_sensitive: bool = False,
        whole_word: bool = True,
        minimum_matches: int = 1,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        if not isinstance(topics, Mapping):
            raise TypeError("topics must be a mapping.")

        if len(topics) > MAX_TOPICS:
            raise ValueError(
                f"At most {MAX_TOPICS} topics are allowed."
            )

        if not isinstance(case_sensitive, bool):
            raise ValueError("case_sensitive must be a boolean.")

        if not isinstance(whole_word, bool):
            raise ValueError("whole_word must be a boolean.")

        if (
            isinstance(minimum_matches, bool)
            or not isinstance(minimum_matches, int)
            or minimum_matches < 1
        ):
            raise ValueError(
                "minimum_matches must be a positive integer."
            )

        self.case_sensitive = case_sensitive
        self.whole_word = whole_word
        self.minimum_matches = minimum_matches

        self.topics = self._validate_topics(topics)
        self._patterns = self._compile_patterns()

    @staticmethod
    def _validate_topics(
        topics: Mapping[str, Sequence[str]],
    ) -> dict[str, tuple[str, ...]]:
        validated: dict[str, tuple[str, ...]] = {}
        total_terms = 0

        for topic, terms in topics.items():
            if not isinstance(topic, str) or not topic.strip():
                raise ValueError(
                    "Topic names must be non-empty strings."
                )

            topic_name = topic.strip()

            if len(topic_name) > 128:
                raise ValueError(
                    "Topic names cannot exceed 128 characters."
                )

            if topic_name in validated:
                raise ValueError(
                    f"Duplicate topic: {topic_name!r}."
                )

            if isinstance(terms, (str, bytes)):
                raise TypeError(
                    f"Terms for {topic_name!r} must be a sequence, "
                    "not a string."
                )

            if not isinstance(terms, Sequence):
                raise TypeError(
                    f"Terms for {topic_name!r} must be a sequence."
                )

            if len(terms) > MAX_TERMS_PER_TOPIC:
                raise ValueError(
                    f"Topic {topic_name!r} exceeds the term limit."
                )

            normalised_terms: list[str] = []

            for term in terms:
                if not isinstance(term, str):
                    raise TypeError("Every topic term must be a string.")

                term = term.strip()

                if not term:
                    raise ValueError("Topic terms cannot be empty.")

                if len(term) > MAX_TERM_LENGTH:
                    raise ValueError(
                        f"Topic terms cannot exceed {MAX_TERM_LENGTH} "
                        "characters."
                    )

                if term not in normalised_terms:
                    normalised_terms.append(term)

            validated[topic_name] = tuple(normalised_terms)
            total_terms += len(normalised_terms)

        if total_terms > MAX_TOTAL_TERMS:
            raise ValueError(
                f"At most {MAX_TOTAL_TERMS} total terms are allowed."
            )

        return validated

    def _compile_patterns(
        self,
    ) -> dict[str, tuple[tuple[str, re.Pattern[str]], ...]]:
        """Compile topic terms into reusable regular expressions."""
        flags = 0 if self.case_sensitive else re.IGNORECASE

        compiled: dict[
            str,
            tuple[tuple[str, re.Pattern[str]], ...],
        ] = {}

        for topic, terms in self.topics.items():
            patterns = []

            for term in terms:
                expression = re.escape(term)

                if self.whole_word:
                    expression = rf"(?<!\w){expression}(?!\w)"

                patterns.append(
                    (term, re.compile(expression, flags))
                )

            compiled[topic] = tuple(patterns)

        return compiled

    @staticmethod
    def _extract_content(
        classification_input: ClassificationInput,
    ) -> str:
        """Combine searchable message text and caption."""
        return "\n".join(
            value
            for value in (
                classification_input.text,
                classification_input.caption,
            )
            if isinstance(value, str) and value
        )

    def _match_topics(
        self,
        content: str,
    ) -> dict[str, tuple[str, ...]]:
        """Return matching terms grouped by topic."""
        matches: dict[str, tuple[str, ...]] = {}

        for topic, patterns in self._patterns.items():
            matched_terms = tuple(
                term
                for term, pattern in patterns
                if pattern.search(content)
            )

            if len(matched_terms) >= self.minimum_matches:
                matches[topic] = matched_terms

        return matches

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Assign topic labels to a message."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Topic classifier is disabled.",
            )

        try:
            content = self._extract_content(
                classification_input
            )

            if not content:
                return self.skipped_result(
                    classifier=self.name,
                    reason="Message contains no searchable text.",
                )

            matches = self._match_topics(content)

            labels = tuple(
                ClassificationLabel(
                    name=topic,
                    category="topic",
                    confidence=1.0,
                )
                for topic in matches
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
                    "matched_topics": {
                        topic: list(terms)
                        for topic, terms in matches.items()
                    },
                    "minimum_matches": self.minimum_matches,
                    "case_sensitive": self.case_sensitive,
                    "whole_word": self.whole_word,
                },
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Topic classification failed",
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
