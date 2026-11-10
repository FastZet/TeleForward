"""
TeleForward formatting transformation.

Normalises whitespace, line endings, paragraph spacing, and common
Markdown formatting in Telegram message text and captions.
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

MAX_CONSECUTIVE_NEWLINES = 10

HORIZONTAL_WHITESPACE_PATTERN = re.compile(
    r"[^\S\n]+",
    flags=re.UNICODE,
)

EXCESSIVE_NEWLINES_PATTERN = re.compile(
    r"\n{3,}"
)

MARKDOWN_LINK_PATTERN = re.compile(
    r"(?<!!)\[([^\]]+)\]\((https?://[^)\s]+)\)"
)

MARKDOWN_IMAGE_PATTERN = re.compile(
    r"!\[([^\]]*)\]\((https?://[^)\s]+)\)"
)

MARKDOWN_HEADING_PATTERN = re.compile(
    r"^(#{1,6})[ \t]+",
    flags=re.MULTILINE,
)

MARKDOWN_BLOCKQUOTE_PATTERN = re.compile(
    r"^[ \t]*>[ \t]?",
    flags=re.MULTILINE,
)

MARKDOWN_LIST_PATTERN = re.compile(
    r"^([ \t]*)[-*+][ \t]+",
    flags=re.MULTILINE,
)

MARKDOWN_NUMBERED_LIST_PATTERN = re.compile(
    r"^([ \t]*)\d+\.[ \t]+",
    flags=re.MULTILINE,
)

MARKDOWN_CODE_FENCE_PATTERN = re.compile(
    r"```(?:[a-zA-Z0-9_+-]+)?[ \t]*\n?"
)

MARKDOWN_INLINE_CODE_PATTERN = re.compile(
    r"`([^`\n]+)`"
)

MARKDOWN_STRIKETHROUGH_PATTERN = re.compile(
    r"~~(.*?)~~"
)

MARKDOWN_BOLD_PATTERN = re.compile(
    r"(?<!\*)\*\*(.+?)\*\*(?!\*)"
)

MARKDOWN_UNDERLINE_PATTERN = re.compile(
    r"__(.+?)__"
)

MARKDOWN_ITALIC_PATTERN = re.compile(
    r"(?<!\*)\*([^*\n]+)\*(?!\*)"
)

MARKDOWN_ITALIC_UNDERSCORE_PATTERN = re.compile(
    r"(?<!\w)_([^_\n]+)_(?!\w)"
)


class FormattingTransformation(BaseTransformation):
    """Normalise text formatting in Telegram messages and captions."""

    name = "formatting"
    version = "1.0.0"

    def __init__(
        self,
        *,
        normalise_line_endings: bool = True,
        collapse_horizontal_whitespace: bool = False,
        trim_lines: bool = False,
        trim_content: bool = True,
        max_consecutive_newlines: int | None = 2,
        strip_markdown: bool = False,
        preserve_link_urls: bool = True,
        preserve_image_alt_text: bool = True,
        remove_blockquote_markers: bool = False,
        normalise_list_markers: bool = False,
        apply_to_text: bool = True,
        apply_to_caption: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__(enabled=enabled)

        boolean_options = {
            "normalise_line_endings": normalise_line_endings,
            "collapse_horizontal_whitespace": (
                collapse_horizontal_whitespace
            ),
            "trim_lines": trim_lines,
            "trim_content": trim_content,
            "strip_markdown": strip_markdown,
            "preserve_link_urls": preserve_link_urls,
            "preserve_image_alt_text": preserve_image_alt_text,
            "remove_blockquote_markers": remove_blockquote_markers,
            "normalise_list_markers": normalise_list_markers,
            "apply_to_text": apply_to_text,
            "apply_to_caption": apply_to_caption,
        }

        for name, value in boolean_options.items():
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a boolean.")

        if max_consecutive_newlines is not None:
            if (
                not isinstance(max_consecutive_newlines, int)
                or isinstance(max_consecutive_newlines, bool)
            ):
                raise ValueError(
                    "max_consecutive_newlines must be an integer or None."
                )

            if not 0 <= max_consecutive_newlines <= (
                MAX_CONSECUTIVE_NEWLINES
            ):
                raise ValueError(
                    "max_consecutive_newlines must be between "
                    f"0 and {MAX_CONSECUTIVE_NEWLINES}."
                )

        self.normalise_line_endings = normalise_line_endings
        self.collapse_horizontal_whitespace = (
            collapse_horizontal_whitespace
        )
        self.trim_lines = trim_lines
        self.trim_content = trim_content
        self.max_consecutive_newlines = max_consecutive_newlines
        self.strip_markdown = strip_markdown
        self.preserve_link_urls = preserve_link_urls
        self.preserve_image_alt_text = preserve_image_alt_text
        self.remove_blockquote_markers = remove_blockquote_markers
        self.normalise_list_markers = normalise_list_markers
        self.apply_to_text = apply_to_text
        self.apply_to_caption = apply_to_caption

    def _strip_markdown(self, content: str) -> str:
        """Remove common Markdown syntax while preserving readable text."""

        if self.preserve_image_alt_text:
            content = MARKDOWN_IMAGE_PATTERN.sub(
                lambda match: match.group(1),
                content,
            )
        else:
            content = MARKDOWN_IMAGE_PATTERN.sub("", content)

        if self.preserve_link_urls:
            content = MARKDOWN_LINK_PATTERN.sub(
                lambda match: (
                    f"{match.group(1)} ({match.group(2)})"
                ),
                content,
            )
        else:
            content = MARKDOWN_LINK_PATTERN.sub(
                lambda match: match.group(1),
                content,
            )

        content = MARKDOWN_CODE_FENCE_PATTERN.sub("", content)

        content = MARKDOWN_INLINE_CODE_PATTERN.sub(
            lambda match: match.group(1),
            content,
        )

        content = MARKDOWN_HEADING_PATTERN.sub("", content)

        content = MARKDOWN_BLOCKQUOTE_PATTERN.sub("", content)

        content = MARKDOWN_LIST_PATTERN.sub(
            r"\1• ",
            content,
        )

        content = MARKDOWN_NUMBERED_LIST_PATTERN.sub(
            r"\1• ",
            content,
        )

        content = MARKDOWN_STRIKETHROUGH_PATTERN.sub(
            r"\1",
            content,
        )

        content = MARKDOWN_BOLD_PATTERN.sub(
            r"\1",
            content,
        )

        content = MARKDOWN_UNDERLINE_PATTERN.sub(
            r"\1",
            content,
        )

        content = MARKDOWN_ITALIC_PATTERN.sub(
            r"\1",
            content,
        )

        content = MARKDOWN_ITALIC_UNDERSCORE_PATTERN.sub(
            r"\1",
            content,
        )

        return content

    def _transform_content(self, content: str) -> str:
        """Apply configured formatting operations."""

        if not content:
            return content

        if self.normalise_line_endings:
            content = content.replace("\r\n", "\n")
            content = content.replace("\r", "\n")

        if self.strip_markdown:
            content = self._strip_markdown(content)

        if self.remove_blockquote_markers:
            content = MARKDOWN_BLOCKQUOTE_PATTERN.sub(
                "",
                content,
            )

        if self.normalise_list_markers:
            content = MARKDOWN_LIST_PATTERN.sub(
                r"\1• ",
                content,
            )

            content = MARKDOWN_NUMBERED_LIST_PATTERN.sub(
                r"\1• ",
                content,
            )

        if self.trim_lines:
            content = "\n".join(
                line.strip()
                for line in content.split("\n")
            )

        if self.collapse_horizontal_whitespace:
            content = HORIZONTAL_WHITESPACE_PATTERN.sub(
                " ",
                content,
            )

        if self.max_consecutive_newlines is not None:
            maximum = self.max_consecutive_newlines

            if maximum == 0:
                content = content.replace("\n", "")
            else:
                content = EXCESSIVE_NEWLINES_PATTERN.sub(
                    "\n" * maximum,
                    content,
                )

        if self.trim_content:
            content = content.strip()

        return content

    async def transform(
        self,
        transformation_input: TransformationInput,
    ) -> TransformationOutput:
        """Transform formatting in message text and captions."""

        started_at = time.perf_counter()

        if not self.enabled:
            return self.skipped_result(
                transformation_input,
                reason="Formatting transformation is disabled.",
            )

        try:
            text = transformation_input.text
            caption = transformation_input.caption

            if self.apply_to_text:
                text = self._transform_content(text)

            if self.apply_to_caption:
                caption = self._transform_content(caption)

            return self.build_result(
                transformation_input,
                text=text,
                caption=caption,
                metadata={
                    "markdown_stripped": self.strip_markdown,
                    "line_endings_normalised": (
                        self.normalise_line_endings
                    ),
                    "horizontal_whitespace_collapsed": (
                        self.collapse_horizontal_whitespace
                    ),
                    "lines_trimmed": self.trim_lines,
                    "content_trimmed": self.trim_content,
                },
                started_at=started_at,
            )

        except Exception as exc:
            elapsed_ms = (
                time.perf_counter() - started_at
            ) * 1000

            logger.exception(
                "Formatting transformation failed",
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
