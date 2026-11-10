"""
TeleForward duplicate-message classifier.

Generates deterministic content fingerprints and identifies potential
duplicate messages using exact and normalised text comparisons.

This classifier performs in-memory comparison against previously
registered fingerprints. Persistent duplicate detection requires
database-backed fingerprint storage.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata

from collections import OrderedDict
from collections.abc import Sequence
from difflib import SequenceMatcher

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)


logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 100_000
MAX_FINGERPRINTS = 100_000
MAX_HISTORY_CANDIDATES = 100
MAX_SIMILARITY_CANDIDATES = 500


class DuplicateClassifier(BaseClassifier):
    """
    Detect duplicate messages using content fingerprints.

    The fingerprint history belongs to this classifier instance.
    It is not shared across processes or persisted automatically.
    """

    name = "duplicate"
    version = "1.0.0"

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.95,
        normalise_whitespace: bool = True,
        normalise_case: bool = True,
        remove_punctuation: bool = False,
        max_history: int = 10_000,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        if (
            isinstance(similarity_threshold, bool)
            or not isinstance(similarity_threshold, (int, float))
            or not 0.0 < similarity_threshold <= 1.0
        ):
            raise ValueError(
                "similarity_threshold must be greater than 0 "
                "and at most 1."
            )

        for name, value in (
            ("normalise_whitespace", normalise_whitespace),
            ("normalise_case", normalise_case),
            ("remove_punctuation", remove_punctuation),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean.")

        if (
            isinstance(max_history, bool)
            or not isinstance(max_history, int)
            or not 1 <= max_history <= MAX_FINGERPRINTS
        ):
            raise ValueError(
                f"max_history must be between 1 and {MAX_FINGERPRINTS}."
            )

        self.similarity_threshold = float(similarity_threshold)
        self.normalise_whitespace = normalise_whitespace
        self.normalise_case = normalise_case
        self.remove_punctuation = remove_punctuation
        self.max_history = max_history

        # fingerprint -> message ID
        self._history: OrderedDict[str, int] = OrderedDict()

        # message ID -> fingerprint
        self._message_fingerprints: dict[int, str] = {}

    @staticmethod
    def _extract_content(
        classification_input: ClassificationInput,
    ) -> str:
        """Combine searchable message text and caption."""
        content = "\n".join(
            value
            for value in (
                classification_input.text,
                classification_input.caption,
            )
            if isinstance(value, str) and value
        )

        return content[:MAX_CONTENT_LENGTH]

    def _normalise_content(self, content: str) -> str:
        """Apply configured text normalisation."""
        normalised = unicodedata.normalize("NFKC", content)

        if self.normalise_case:
            normalised = normalised.casefold()

        if self.remove_punctuation:
            normalised = "".join(
                character
                for character in normalised
                if not unicodedata.category(character).startswith("P")
            )

        if self.normalise_whitespace:
            normalised = re.sub(r"\s+", " ", normalised).strip()

        return normalised

    @staticmethod
    def _generate_fingerprint(content: str) -> str:
        """Generate a deterministic SHA-256 fingerprint."""
        return hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()

    def _find_exact_duplicate(
        self,
        fingerprint: str,
        current_message_id: int,
    ) -> int | None:
        """Find a previously registered exact duplicate."""
        message_id = self._history.get(fingerprint)

        if message_id == current_message_id:
            return None

        return message_id

    def _find_similar_duplicate(
        self,
        content: str,
        current_message_id: int,
    ) -> tuple[int, float] | None:
        """
        Find the closest similar message in recent history.

        SequenceMatcher is used for a bounded candidate set. This is
        intended for short message histories, not large-scale
        similarity search.
        """
        best_match: tuple[int, float] | None = None

        candidates = list(self._history.items())[
            -MAX_SIMILARITY_CANDIDATES:
        ]

        for fingerprint, message_id in reversed(candidates):
            if message_id == current_message_id:
                continue

            previous_content = getattr(
                self,
                "_content_cache",
                {},
            ).get(fingerprint)

            if previous_content is None:
                continue

            similarity = SequenceMatcher(
                None,
                content,
                previous_content,
                autojunk=False,
            ).ratio()

            if (
                similarity >= self.similarity_threshold
                and (
                    best_match is None
                    or similarity > best_match[1]
                )
            ):
                best_match = (message_id, similarity)

        return best_match

    def _remember(
        self,
        fingerprint: str,
        message_id: int,
        content: str,
    ) -> None:
        """Store a fingerprint and maintain bounded history."""
        if not hasattr(self, "_content_cache"):
            self._content_cache: dict[str, str] = {}

        previous_fingerprint = self._message_fingerprints.get(
            message_id
        )

        if previous_fingerprint is not None:
            if self._history.get(previous_fingerprint) == message_id:
                self._history.pop(previous_fingerprint, None)

            self._content_cache.pop(previous_fingerprint, None)

        self._history[fingerprint] = message_id
        self._content_cache[fingerprint] = content
        self._message_fingerprints[message_id] = fingerprint

        self._history.move_to_end(fingerprint)

        while len(self._history) > self.max_history:
            expired_fingerprint, expired_message_id = (
                self._history.popitem(last=False)
            )

            self._content_cache.pop(expired_fingerprint, None)

            if (
                self._message_fingerprints.get(expired_message_id)
                == expired_fingerprint
            ):
                self._message_fingerprints.pop(
                    expired_message_id,
                    None,
                )

    def clear_history(self) -> None:
        """Clear all in-memory duplicate fingerprints."""
        self._history.clear()
        self._message_fingerprints.clear()
        self._content_cache.clear()

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Determine whether a message duplicates recent content."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Duplicate classifier is disabled.",
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

            normalised = self._normalise_content(content)

            if not normalised:
                return self.skipped_result(
                    classifier=self.name,
                    reason="Normalised message content is empty.",
                )

            fingerprint = self._generate_fingerprint(normalised)

            exact_duplicate_id = self._find_exact_duplicate(
                fingerprint,
                classification_input.message_id,
            )

            similarity_match = None

            if exact_duplicate_id is None:
                similarity_match = self._find_similar_duplicate(
                    normalised,
                    classification_input.message_id,
                )

            is_duplicate = (
                exact_duplicate_id is not None
                or similarity_match is not None
            )

            duplicate_message_id = (
                exact_duplicate_id
                if exact_duplicate_id is not None
                else (
                    similarity_match[0]
                    if similarity_match is not None
                    else None
                )
            )

            confidence = (
                1.0
                if exact_duplicate_id is not None
                else (
                    similarity_match[1]
                    if similarity_match is not None
                    else 1.0
                )
            )

            labels = self.filter_by_confidence(
                (
                    ClassificationLabel(
                        name=(
                            "duplicate"
                            if is_duplicate
                            else "unique"
                        ),
                        category="duplicate_status",
                        confidence=confidence,
                    ),
                )
            )

            primary_label = labels[0] if labels else None

            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            result = ClassificationResult(
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
                    "is_duplicate": is_duplicate,
                    "duplicate_message_id": duplicate_message_id,
                    "fingerprint": fingerprint,
                    "comparison_method": (
                        "exact"
                        if exact_duplicate_id is not None
                        else (
                            "similarity"
                            if similarity_match is not None
                            else "none"
                        )
                    ),
                    "similarity_threshold": self.similarity_threshold,
                    "history_size": len(self._history),
                },
            )

            # Remember only non-duplicate messages.
            if not is_duplicate:
                self._remember(
                    fingerprint,
                    classification_input.message_id,
                    normalised,
                )

            return result

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Duplicate classification failed",
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
