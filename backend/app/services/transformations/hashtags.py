"""
TeleForward hashtag transformation.

Supports hashtag extraction, removal, replacement, normalisation,
and allowlist/blocklist filtering.
"""

from __future__ import annotations

import logging
import re
import time

from app.services.transformations.base import (
    BaseTransformation,
    TransformationInput,
    TransformationOutput,
    TransformationStatus,
)

logger = logging.getLogger(__name__)

MAX_HASHTAGS = 500
MAX_HASHTAG_LENGTH = 128

HASHTAG_PATTERN = re.compile(
    r"(?<![\w#])#([^\W#][\w]*)",
    flags=re.UNICODE,
)


class HashtagTransformation(BaseTransformation):
    """Transform hashtags in Telegram message text and captions."""

    name = "hashtags"
    version = "1.0.0"

    def __init__(
        self,
        *,
        remove_hashtags: bool = False,
        lowercase: bool = False,
        uppercase: bool = False,
        remove_duplicates: bool = False,
        allowed_hashtags: set[str] | None = None,
        blocked_hashtags: set[str] | None = None,
        replacements: dict[str, str] | None = None,
        replacement_case_sensitive: bool = False,
        preserve_hashtag_marker: bool = True,
        apply_to_text: bool = True,
        apply_to_caption: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)

        if lowercase and uppercase:
            raise ValueError(
                "lowercase and uppercase cannot both be enabled."
            )

        boolean_options = {
            "remove_hashtags": remove_hashtags,
            "lowercase": lowercase,
            "uppercase": uppercase,
            "remove_duplicates": remove_duplicates,
            "replacement_case_sensitive": replacement_case_sensitive,
            "preserve_hashtag_marker": preserve_hashtag_marker,
            "apply_to_text": apply_to_text,
            "apply_to_caption": apply_to_caption,
        }

        for name, value in boolean_options.items():
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean.")

        self.remove_hashtags = remove_hashtags
        self.lowercase = lowercase
        self.uppercase = uppercase
        self.remove_duplicates = remove_duplicates
        self.replacement_case_sensitive = replacement_case_sensitive
        self.preserve_hashtag_marker = preserve_hashtag_marker
        self.apply_to_text = apply_to_text
        self.apply_to_caption = apply_to_caption

        self.allowed_hashtags = self._normalise_set(
            allowed_hashtags
        )
        self.blocked_hashtags = self._normalise_set(
            blocked_hashtags
        )
        self.replacements = self._normalise_replacements(
            replacements
        )

    @staticmethod
    def _normalise_hashtag(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("Hashtags must be strings.")

        value = value.strip()

        if value.startswith("#"):
            value = value[1:]

        if not value:
            raise ValueError("Hashtag cannot be empty.")

        if len(value) > MAX_HASHTAG_LENGTH:
            raise ValueError("Hashtag is too long.")

        if not re.fullmatch(r"[\w]+", value, flags=re.UNICODE):
            raise ValueError(
                f"Invalid hashtag value: {value!r}"
            )

        return value

    @classmethod
    def _normalise_set(
        cls,
        values: set[str] | None,
    ) -> frozenset[str] | None:
        if values is None:
            return None

        if not isinstance(values, set):
            raise TypeError("Hashtag collections must be sets.")

        if len(values) > MAX_HASHTAGS:
            raise ValueError(
                f"At most {MAX_HASHTAGS} hashtags are allowed."
            )

        return frozenset(
            cls._normalise_hashtag(value).casefold()
            for value in values
        )

    @classmethod
    def _normalise_replacements(
        cls,
        replacements: dict[str, str] | None,
    ) -> dict[str, str]:
        if replacements is None:
            return {}

        if not isinstance(replacements, dict):
            raise TypeError(
                "replacements must be a dictionary."
            )

        if len(replacements) > MAX_HASHTAGS:
            raise ValueError(
                f"At most {MAX_HASHTAGS} replacements are allowed."
            )

        result: dict[str, str] = {}

        for source, destination in replacements.items():
            source_value = cls._normalise_hashtag(source)
            destination_value = cls._normalise_hashtag(destination)

            if not destination_value:
                raise ValueError(
                    "Replacement hashtags cannot be empty."
                )

            result[source_value] = destination_value

        return result

    def _find_replacement(self, hashtag: str) -> str | None:
        """Find a configured replacement for a hashtag."""
        if self.replacement_case_sensitive:
            return self.replacements.get(hashtag)

        folded = hashtag.casefold()

        for source, destination in self.replacements.items():
            if source.casefold() == folded:
                return destination

        return None

    def _transform_content(
        self,
        content: str,
    ) -> tuple[str, int, list[str]]:
        """Transform hashtags in a content string."""
        if not content:
            return content, 0, []

        matches = list(HASHTAG_PATTERN.finditer(content))

        if len(matches) > MAX_HASHTAGS:
            raise ValueError(
                f"Content contains more than {MAX_HASHTAGS} hashtags."
            )

        if not matches:
            return content, 0, []

        output: list[str] = []
        previous_end = 0

        seen: set[str] = set()
        extracted: list[str] = []
        transformed_count = 0

        for match in matches:
            original = match.group(1)
            normalised = original

            output.append(content[previous_end:match.start()])

            extracted.append(original)

            if self.remove_hashtags:
                transformed_count += 1
                previous_end = match.end()
                continue

            if self.allowed_hashtags is not None:
                if original.casefold() not in self.allowed_hashtags:
                    transformed_count += 1
                    previous_end = match.end()
                    continue

            if original.casefold() in self.blocked_hashtags:
                transformed_count += 1
                previous_end = match.end()
                continue

            replacement = self._find_replacement(normalised)

            if replacement is not None:
                normalised = replacement

            if self.lowercase:
                normalised = normalised.lower()
            elif self.uppercase:
                normalised = normalised.upper()

            duplicate_key = normalised.casefold()

            if self.remove_duplicates and duplicate_key in seen:
                transformed_count += 1
                previous_end = match.end()
                continue

            seen.add(duplicate_key)

            marker = "#" if self.preserve_hashtag_marker else ""
            replacement_value = marker + normalised

            if replacement_value != match.group(0):
                transformed_count += 1

            output.append(replacement_value)
            previous_end = match.end()

        output.append(content[previous_end:])

        return (
            "".join(output),
            transformed_count,
            extracted,
        )

    async def transform(
        self,
        transformation_input: TransformationInput,
    ) -> TransformationOutput:
        """Transform hashtags in message text and captions."""
        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                transformation_input,
                reason="Hashtag transformation is disabled.",
            )

        try:
            text = transformation_input.text
            caption = transformation_input.caption

            text_count = 0
            caption_count = 0
            text_hashtags: list[str] = []
            caption_hashtags: list[str] = []

            if self.apply_to_text:
                text, text_count, text_hashtags = (
                    self._transform_content(text)
                )

            if self.apply_to_caption:
                caption, caption_count, caption_hashtags = (
                    self._transform_content(caption)
                )

            return self.build_result(
                transformation_input,
                text=text,
                caption=caption,
                metadata={
                    "text_hashtag_count": len(text_hashtags),
                    "caption_hashtag_count": len(caption_hashtags),
                    "text_hashtags": text_hashtags,
                    "caption_hashtags": caption_hashtags,
                    "text_transformations": text_count,
                    "caption_transformations": caption_count,
                    "total_transformations": (
                        text_count + caption_count
                    ),
                },
                started_at=started_at,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Hashtag transformation failed",
                extra={
                    "message_id": transformation_input.message_id,
                },
            )

            return TransformationOutput(
                transformation=self.name,
                status=TransformationStatus.FAILED,
                text=transformation_input.text,
                caption=transformation_input.caption,
                changed=False,
                processing_time_ms=elapsed_ms,
                error=str(exc)[:2000],
                metadata={
                    "error_type": type(exc).__name__,
                },
            )
