"""
TeleForward language classifier.

Provides lightweight language detection using Unicode script
distribution and configurable language keyword dictionaries.

This classifier is heuristic-based and should not be treated as
a replacement for a dedicated language identification model.
"""

from __future__ import annotations

import logging
import time

from collections import Counter
from collections.abc import Mapping, Sequence
from unicodedata import name as unicode_name

from app.services.classification.base import (
    BaseClassifier,
    ClassificationInput,
    ClassificationLabel,
    ClassificationResult,
    ClassificationStatus,
)


logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 100_000
MAX_LANGUAGES = 100
MAX_KEYWORDS_PER_LANGUAGE = 200
MAX_TOTAL_KEYWORDS = 2_000
MAX_KEYWORD_LENGTH = 128

# Unicode script names mapped to ISO 639-1 language codes.
# A script alone cannot reliably distinguish languages that share it.
SCRIPT_LANGUAGE_HINTS: dict[str, str] = {
    "DEVANAGARI": "hi",
    "BENGALI": "bn",
    "GURMUKHI": "pa",
    "GUJARATI": "gu",
    "ORIYA": "or",
    "TAMIL": "ta",
    "TELUGU": "te",
    "KANNADA": "kn",
    "MALAYALAM": "ml",
    "THAI": "th",
    "ARMENIAN": "hy",
    "GEORGIAN": "ka",
    "GREEK": "el",
    "HEBREW": "he",
    "ARABIC": "ar",
    "HIRAGANA": "ja",
    "KATAKANA": "ja",
    "HANGUL": "ko",
    "CYRILLIC": "ru",
}

DEFAULT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "en": (
        "the", "and", "this", "that", "with",
        "from", "have", "you", "your", "for",
    ),
    "hi": (
        "और", "है", "हैं", "का", "की",
        "के", "में", "यह", "एक", "नहीं",
    ),
    "bn": (
        "এবং", "এই", "যে", "না", "একটি",
        "করে", "হয়", "আমি", "আপনি", "আমরা",
    ),
    "as": (
        "আৰু", "এই", "যে", "নহয়", "কৰা",
        "হয়", "মই", "আপুনি", "তেওঁ", "এটা",
    ),
}


class LanguageClassifier(BaseClassifier):
    """Classify message language using lightweight heuristics."""

    name = "language"
    version = "1.0.0"

    def __init__(
        self,
        *,
        language_keywords: Mapping[
            str,
            Sequence[str],
        ] | None = None,
        minimum_keyword_matches: int = 1,
        minimum_script_ratio: float = 0.5,
        enabled: bool = True,
        minimum_confidence: float = 0.0,
    ) -> None:
        super().__init__(
            enabled=enabled,
            minimum_confidence=minimum_confidence,
        )

        if (
            isinstance(minimum_keyword_matches, bool)
            or not isinstance(minimum_keyword_matches, int)
            or minimum_keyword_matches < 1
        ):
            raise ValueError(
                "minimum_keyword_matches must be a positive integer."
            )

        if (
            isinstance(minimum_script_ratio, bool)
            or not isinstance(minimum_script_ratio, (int, float))
            or not 0.0 < minimum_script_ratio <= 1.0
        ):
            raise ValueError(
                "minimum_script_ratio must be between 0 and 1."
            )

        self.minimum_keyword_matches = minimum_keyword_matches
        self.minimum_script_ratio = float(minimum_script_ratio)

        configured_keywords = (
            DEFAULT_KEYWORDS
            if language_keywords is None
            else language_keywords
        )

        self.language_keywords = self._validate_keywords(
            configured_keywords
        )

    @staticmethod
    def _validate_keywords(
        language_keywords: Mapping[str, Sequence[str]],
    ) -> dict[str, tuple[str, ...]]:
        """Validate language codes and their keyword dictionaries."""
        if not isinstance(language_keywords, Mapping):
            raise TypeError(
                "language_keywords must be a mapping."
            )

        if len(language_keywords) > MAX_LANGUAGES:
            raise ValueError(
                f"At most {MAX_LANGUAGES} languages are allowed."
            )

        validated: dict[str, tuple[str, ...]] = {}
        total_keywords = 0

        for language, keywords in language_keywords.items():
            if not isinstance(language, str):
                raise TypeError("Language codes must be strings.")

            code = language.strip().lower()

            if (
                len(code) < 2
                or len(code) > 3
                or not code.isalpha()
            ):
                raise ValueError(
                    f"Invalid language code: {language!r}."
                )

            if code in validated:
                raise ValueError(
                    f"Duplicate language code: {code!r}."
                )

            if isinstance(keywords, (str, bytes)):
                raise TypeError(
                    f"Keywords for {code!r} must be a sequence."
                )

            if not isinstance(keywords, Sequence):
                raise TypeError(
                    f"Keywords for {code!r} must be a sequence."
                )

            if len(keywords) > MAX_KEYWORDS_PER_LANGUAGE:
                raise ValueError(
                    f"Language {code!r} exceeds the keyword limit."
                )

            terms: list[str] = []

            for keyword in keywords:
                if not isinstance(keyword, str):
                    raise TypeError(
                        "Language keywords must be strings."
                    )

                keyword = keyword.strip()

                if not keyword:
                    raise ValueError(
                        "Language keywords cannot be empty."
                    )

                if len(keyword) > MAX_KEYWORD_LENGTH:
                    raise ValueError(
                        "Language keywords cannot exceed "
                        f"{MAX_KEYWORD_LENGTH} characters."
                    )

                if keyword not in terms:
                    terms.append(keyword)

            validated[code] = tuple(terms)
            total_keywords += len(terms)

        if total_keywords > MAX_TOTAL_KEYWORDS:
            raise ValueError(
                f"At most {MAX_TOTAL_KEYWORDS} total keywords "
                "are allowed."
            )

        return validated

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
    def _script_distribution(
        content: str,
    ) -> Counter[str]:
        """Count Unicode scripts among alphabetic characters."""
        scripts: Counter[str] = Counter()

        for character in content:
            if not character.isalpha():
                continue

            try:
                character_name = unicode_name(character)
            except ValueError:
                continue

            script = character_name.split(" ", 1)[0]
            scripts[script] += 1

        return scripts

    def _detect_script_language(
        self,
        content: str,
    ) -> tuple[str | None, float, str | None]:
        """
        Infer a language hint from the dominant Unicode script.

        Latin and shared scripts are deliberately not mapped to a
        language because script identification alone is insufficient.
        """
        distribution = self._script_distribution(content)
        total = sum(distribution.values())

        if total == 0:
            return None, 0.0, None

        script, count = distribution.most_common(1)[0]
        ratio = count / total

        if ratio < self.minimum_script_ratio:
            return None, ratio, script

        language = SCRIPT_LANGUAGE_HINTS.get(script)

        return language, ratio, script

    def _detect_keyword_language(
        self,
        content: str,
    ) -> tuple[str | None, float, dict[str, int]]:
        """Identify the language with the strongest keyword evidence."""
        normalised_content = content.casefold()
        word_counts: dict[str, int] = {}

        for language, keywords in self.language_keywords.items():
            count = sum(
                normalised_content.count(keyword.casefold())
                for keyword in keywords
            )

            if count:
                word_counts[language] = count

        if not word_counts:
            return None, 0.0, {}

        ranked = sorted(
            word_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )

        best_language, best_count = ranked[0]
        total_matches = sum(word_counts.values())

        confidence = best_count / total_matches

        return best_language, confidence, word_counts

    async def classify(
        self,
        classification_input: ClassificationInput,
    ) -> ClassificationResult:
        """Detect the likely language of a Telegram message."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                classifier=self.name,
                reason="Language classifier is disabled.",
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

            script_language, script_ratio, dominant_script = (
                self._detect_script_language(content)
            )

            keyword_language, keyword_confidence, keyword_counts = (
                self._detect_keyword_language(content)
            )

            detected_language: str | None = None
            confidence = 0.0
            detection_method = "unresolved"

            # Prefer a sufficiently dominant, identifiable script.
            if script_language is not None:
                detected_language = script_language
                confidence = script_ratio
                detection_method = "unicode_script"

            elif (
                keyword_language is not None
                and keyword_counts.get(keyword_language, 0)
                >= self.minimum_keyword_matches
            ):
                detected_language = keyword_language
                confidence = keyword_confidence
                detection_method = "keyword_dictionary"

            if detected_language is None:
                return self.skipped_result(
                    classifier=self.name,
                    reason="Language could not be identified reliably.",
                )

            label = ClassificationLabel(
                name=detected_language,
                category="language",
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
                    "detected_language": detected_language,
                    "detection_method": detection_method,
                    "dominant_script": dominant_script,
                    "script_ratio": round(script_ratio, 4),
                    "keyword_confidence": round(
                        keyword_confidence,
                        4,
                    ),
                    "keyword_match_counts": keyword_counts,
                },
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Language classification failed",
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
