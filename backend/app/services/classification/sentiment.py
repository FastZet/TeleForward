"""
TeleForward sentiment classifier.

Uses configurable positive and negative word or phrase dictionaries
to estimate the sentiment of Telegram messages.
"""

from __future__ import annotations

import logging
import re
import time

from collections.abc import Sequence

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)


logger = logging.getLogger(__name__)

MAX_TERMS_PER_POLARITY = 2_000
MAX_TERM_LENGTH = 128
MAX_CONTENT_LENGTH = 100_000

DEFAULT_POSITIVE_TERMS = (
    "good",
    "great",
    "excellent",
    "amazing",
    "awesome",
    "wonderful",
    "fantastic",
    "love",
    "happy",
    "success",
    "successful",
    "beautiful",
    "perfect",
    "best",
    "brilliant",
    "helpful",
    "thanks",
    "thank you",
    "appreciate",
    "congratulations",
)

DEFAULT_NEGATIVE_TERMS = (
    "bad",
    "terrible",
    "awful",
    "horrible",
    "poor",
    "hate",
    "angry",
    "sad",
    "failure",
    "failed",
    "worst",
    "useless",
    "disappointing",
    "disappointed",
    "problem",
    "error",
    "wrong",
    "broken",
    "fraud",
    "scam",
)


class SentimentClassifier(BaseClassifier):
    """
    Estimate message sentiment using positive and negative lexicons.

    This is a rule-based classifier. It does not understand context,
    sarcasm, negation or linguistic nuance.
    """

    name = "sentiment"
    version = "1.0.0"

    def __init__(
        self,
        *,
        positive_terms: Sequence[str] = DEFAULT_POSITIVE_TERMS,
        negative_terms: Sequence[str] = DEFAULT_NEGATIVE_TERMS,
        case_sensitive: bool = False,
        whole_word: bool = True,
        neutral_threshold: float = 0.15,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        if not isinstance(case_sensitive, bool):
            raise ValueError("case_sensitive must be a boolean.")

        if not isinstance(whole_word, bool):
            raise ValueError("whole_word must be a boolean.")

        if (
            isinstance(neutral_threshold, bool)
            or not isinstance(neutral_threshold, (int, float))
            or not 0.0 <= neutral_threshold <= 1.0
        ):
            raise ValueError(
                "neutral_threshold must be between 0.0 and 1.0."
            )

        self.case_sensitive = case_sensitive
        self.whole_word = whole_word
        self.neutral_threshold = float(neutral_threshold)

        self.positive_terms = self._validate_terms(
            positive_terms,
            "positive_terms",
        )
        self.negative_terms = self._validate_terms(
            negative_terms,
            "negative_terms",
        )

        overlap = set(self.positive_terms) & set(
            self.negative_terms
        )

        if overlap:
            raise ValueError(
                "A term cannot appear in both sentiment dictionaries: "
                + ", ".join(sorted(overlap))
            )

        self._positive_patterns = self._compile_terms(
            self.positive_terms
        )
        self._negative_patterns = self._compile_terms(
            self.negative_terms
        )

    @staticmethod
    def _validate_terms(
        terms: Sequence[str],
        parameter_name: str,
    ) -> tuple[str, ...]:
        """Validate and normalise a sentiment dictionary."""
        if isinstance(terms, (str, bytes)):
            raise TypeError(
                f"{parameter_name} must be a sequence of strings."
            )

        if not isinstance(terms, Sequence):
            raise TypeError(
                f"{parameter_name} must be a sequence of strings."
            )

        if len(terms) > MAX_TERMS_PER_POLARITY:
            raise ValueError(
                f"{parameter_name} exceeds the maximum of "
                f"{MAX_TERMS_PER_POLARITY} terms."
            )

        validated: list[str] = []

        for term in terms:
            if not isinstance(term, str):
                raise TypeError("Every sentiment term must be a string.")

            term = term.strip()

            if not term:
                raise ValueError("Sentiment terms cannot be empty.")

            if len(term) > MAX_TERM_LENGTH:
                raise ValueError(
                    f"Sentiment terms cannot exceed "
                    f"{MAX_TERM_LENGTH} characters."
                )

            if term not in validated:
                validated.append(term)

        return tuple(validated)

    def _compile_terms(
        self,
        terms: Sequence[str],
    ) -> tuple[tuple[str, re.Pattern[str]], ...]:
        """Compile sentiment terms into reusable patterns."""
        flags = 0 if self.case_sensitive else re.IGNORECASE

        patterns = []

        for term in terms:
            expression = re.escape(term)

            if self.whole_word:
                expression = rf"(?<!\w){expression}(?!\w)"

            patterns.append(
                (term, re.compile(expression, flags))
            )

        return tuple(patterns)

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

    @staticmethod
    def _find_matches(
        content: str,
        patterns: Sequence[tuple[str, re.Pattern[str]]],
    ) -> tuple[str, ...]:
        """Return each matched lexicon term once."""
        return tuple(
            term
            for term, pattern in patterns
            if pattern.search(content)
        )

    def _calculate_sentiment(
        self,
        positive_matches: Sequence[str],
        negative_matches: Sequence[str],
    ) -> tuple[str, float, int]:
        """
        Determine sentiment and confidence.

        Confidence is based on the balance between positive and
        negative lexicon matches. It is not a statistical probability.
        """
        positive_count = len(positive_matches)
        negative_count = len(negative_matches)
        total_matches = positive_count + negative_count

        if total_matches == 0:
            return "neutral", 0.0, 0

        score = (
            positive_count - negative_count
        ) / total_matches

        if abs(score) <= self.neutral_threshold:
            return "neutral", 1.0 - abs(score), total_matches

        if score > 0:
            return "positive", score, total_matches

        return "negative", abs(score), total_matches

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Classify the sentiment of a Telegram message."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Sentiment classifier is disabled.",
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

            positive_matches = self._find_matches(
                content,
                self._positive_patterns,
            )

            negative_matches = self._find_matches(
                content,
                self._negative_patterns,
            )

            sentiment, confidence, total_matches = (
                self._calculate_sentiment(
                    positive_matches,
                    negative_matches,
                )
            )

            label = ClassificationLabel(
                name=sentiment,
                category="sentiment",
                confidence=confidence,
            )

            labels = self.filter_by_confidence((label,))

            primary_label = labels[0] if labels else None

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
                    "positive_matches": list(positive_matches),
                    "negative_matches": list(negative_matches),
                    "positive_count": len(positive_matches),
                    "negative_count": len(negative_matches),
                    "total_matches": total_matches,
                    "neutral_threshold": self.neutral_threshold,
                    "method": "lexicon",
                },
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Sentiment classification failed",
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
