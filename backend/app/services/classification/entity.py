"""
TeleForward entity classifier.

Extracts structured entities from Telegram message text and captions
using built-in regular expressions and configurable custom patterns.

This is a pattern-based extractor, not a full NLP named-entity
recognition model.
"""

from __future__ import annotations

import logging
import re
import time

from collections.abc import Mapping

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)


logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 100_000
MAX_CUSTOM_PATTERNS = 100
MAX_PATTERN_LENGTH = 512
MAX_MATCHES_PER_TYPE = 500
MAX_TOTAL_MATCHES = 2_000

BUILTIN_PATTERNS: dict[str, re.Pattern[str]] = {
    "url": re.compile(
        r"(?i)\b(?:https?://|www\.)[^\s<>\[\]{}\"']+"
    ),
    "email": re.compile(
        r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
    ),
    "phone": re.compile(
        r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)"
    ),
    "hashtag": re.compile(
        r"(?<!\w)#[\w]+",
        re.UNICODE,
    ),
    "mention": re.compile(
        r"(?<!\w)@[A-Za-z0-9_]{5,32}"
    ),
}


class EntityClassifier(BaseClassifier):
    """Extract structured entities from message content."""

    name = "entity"
    version = "1.0.0"

    def __init__(
        self,
        *,
        custom_patterns: Mapping[str, str] | None = None,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        if custom_patterns is None:
            custom_patterns = {}

        if not isinstance(custom_patterns, Mapping):
            raise TypeError(
                "custom_patterns must be a mapping."
            )

        if len(custom_patterns) > MAX_CUSTOM_PATTERNS:
            raise ValueError(
                f"At most {MAX_CUSTOM_PATTERNS} custom patterns "
                "are allowed."
            )

        self._patterns = dict(BUILTIN_PATTERNS)
        self._patterns.update(
            self._compile_custom_patterns(custom_patterns)
        )

    @staticmethod
    def _compile_custom_patterns(
        custom_patterns: Mapping[str, str],
    ) -> dict[str, re.Pattern[str]]:
        """Validate and compile custom entity patterns."""
        compiled: dict[str, re.Pattern[str]] = {}

        for entity_type, expression in custom_patterns.items():
            if (
                not isinstance(entity_type, str)
                or not entity_type.strip()
            ):
                raise ValueError(
                    "Custom entity names cannot be empty."
                )

            name = entity_type.strip().lower()

            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
                raise ValueError(
                    f"Invalid custom entity name: {entity_type!r}."
                )

            if name in BUILTIN_PATTERNS:
                raise ValueError(
                    f"Custom entity name {name!r} conflicts "
                    "with a built-in entity."
                )

            if not isinstance(expression, str) or not expression:
                raise ValueError(
                    f"Pattern for {name!r} must be a non-empty string."
                )

            if len(expression) > MAX_PATTERN_LENGTH:
                raise ValueError(
                    f"Pattern for {name!r} exceeds the length limit."
                )

            try:
                compiled[name] = re.compile(expression)
            except re.error as exc:
                raise ValueError(
                    f"Invalid regular expression for {name!r}: {exc}"
                ) from exc

        return compiled

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

    def _extract_entities(
        self,
        content: str,
    ) -> dict[str, tuple[str, ...]]:
        """Extract unique matches for each configured entity type."""
        extracted: dict[str, tuple[str, ...]] = {}
        total_matches = 0

        for entity_type, pattern in self._patterns.items():
            matches: list[str] = []
            seen: set[str] = set()

            for match in pattern.finditer(content):
                value = match.group(0).strip()

                if not value or value in seen:
                    continue

                seen.add(value)
                matches.append(value)

                if len(matches) >= MAX_MATCHES_PER_TYPE:
                    break

                if total_matches + len(matches) >= MAX_TOTAL_MATCHES:
                    break

            if matches:
                extracted[entity_type] = tuple(matches)
                total_matches += len(matches)

            if total_matches >= MAX_TOTAL_MATCHES:
                break

        return extracted

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Extract entities from a Telegram message."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Entity classifier is disabled.",
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

            entities = self._extract_entities(content)

            labels = tuple(
                ClassificationLabel(
                    name=entity_type,
                    category="entity_type",
                    confidence=1.0,
                )
                for entity_type in entities
            )

            labels = self.filter_by_confidence(labels)

            primary_label = (
                labels[0]
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
                    "entities": {
                        entity_type: list(values)
                        for entity_type, values in entities.items()
                    },
                    "entity_counts": {
                        entity_type: len(values)
                        for entity_type, values in entities.items()
                    },
                    "total_entity_types": len(entities),
                    "total_entities": sum(
                        len(values)
                        for values in entities.values()
                    ),
                    "custom_entity_types": sorted(
                        set(self._patterns) - set(BUILTIN_PATTERNS)
                    ),
                },
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Entity classification failed",
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
