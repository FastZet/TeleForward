"""
TeleForward unified message filtering pipeline.

Coordinates individual filtering services and produces a consolidated
filtering decision for Telegram messages.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from app.services.filtering.chat import ChatContext, ChatFilter
from app.services.filtering.date import DateFilter, DateFilterConfig
from app.services.filtering.entities import (
    EntityFilter,
    EntityFilterConfig,
    ExtractedEntity,
)
from app.services.filtering.hashtags import (
    HashtagFilter,
    HashtagFilterConfig,
)
from app.services.filtering.language import (
    LanguageDetection,
    LanguageDetector,
    LanguageFilter,
    LanguageFilterConfig,
)
from app.services.filtering.length import (
    LengthFilter,
    LengthFilterConfig,
)
from app.services.filtering.links import (
    LinkFilter,
    LinkFilterConfig,
)
from app.services.filtering.media import MediaFilter
from app.services.filtering.sender import SenderContext, SenderFilter
from app.services.filtering.text import TextFilter
from app.services.filtering.keywords import (
    KeywordFilter,
    KeywordFilterConfig,
)
from app.services.filtering.engine import (
    FilterContext,
    FilterEngine,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MessageFilterContext:
    """Information required to evaluate a Telegram message."""

    message_id: int
    account_id: int

    text: str = ""
    caption: str = ""

    sender: SenderContext | None = None
    chat: ChatContext | None = None

    message_date: datetime | None = None
    media: Any | None = None
    entities: tuple[ExtractedEntity, ...] = ()

    language_detection: LanguageDetection | None = None

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MessageFilterConfig:
    """Configuration for the unified filtering pipeline."""

    enabled_filters: frozenset[str] = frozenset()

    text_filter: Any | None = None
    media_filter: Any | None = None
    sender_filter: Any | None = None
    chat_filter: Any | None = None
    date_filter: DateFilterConfig | None = None

    length_filter: LengthFilterConfig | None = None
    link_filter: LinkFilterConfig | None = None
    hashtag_filter: HashtagFilterConfig | None = None
    keyword_filter: KeywordFilterConfig | None = None
    entity_filter: EntityFilterConfig | None = None
    language_filter: LanguageFilterConfig | None = None

    stop_on_first_failure: bool = False
    language_detection_timeout: float = 10.0


@dataclass(frozen=True, slots=True)
class FilterCheckResult:
    """Outcome of an individual filter."""

    name: str
    matched: bool
    reason: str
    details: Any | None = None


@dataclass(frozen=True, slots=True)
class MessageFilterResult:
    """Consolidated filtering decision."""

    matched: bool
    message_id: int
    account_id: int
    checks: tuple[FilterCheckResult, ...]
    failed_filters: tuple[str, ...]
    reason: str


class ForwardingFilterPipeline:
    """Execute configured filters against Telegram messages."""

    SUPPORTED_FILTERS = frozenset({
        "text",
        "media",
        "sender",
        "chat",
        "date",
        "length",
        "links",
        "hashtags",
        "keywords",
        "entities",
        "language",
        "advanced",
    })

    def __init__(
        self,
        *,
        language_detector: LanguageDetector | None = None,
    ) -> None:
        self.language_detector = language_detector

        self.text_filter = TextFilter()
        self.media_filter = MediaFilter()
        self.sender_filter = SenderFilter()
        self.chat_filter = ChatFilter()
        self.date_filter = DateFilter()

        self.length_filter = LengthFilter()
        self.link_filter = LinkFilter()
        self.hashtag_filter = HashtagFilter()
        self.keyword_filter = KeywordFilter()
        self.entity_filter = EntityFilter()
        self.language_filter = LanguageFilter()

        self.advanced_filter = FilterEngine()

    @staticmethod
    def _validate_context(context: MessageFilterContext) -> None:
        if (
            isinstance(context.message_id, bool)
            or not isinstance(context.message_id, int)
            or context.message_id <= 0
        ):
            raise ValueError("message_id must be a positive integer.")

        if (
            isinstance(context.account_id, bool)
            or not isinstance(context.account_id, int)
            or context.account_id <= 0
        ):
            raise ValueError("account_id must be a positive integer.")

        if not isinstance(context.text, str):
            raise TypeError("text must be a string.")

        if not isinstance(context.caption, str):
            raise TypeError("caption must be a string.")

        if context.message_date is not None:
            if (
                not isinstance(context.message_date, datetime)
                or context.message_date.tzinfo is None
                or context.message_date.utcoffset() is None
            ):
                raise ValueError(
                    "message_date must be timezone-aware."
                )

        if not isinstance(context.metadata, dict):
            raise TypeError("metadata must be a dictionary.")

    def _validate_config(
        self,
        config: MessageFilterConfig,
    ) -> None:
        if not isinstance(config.enabled_filters, (set, frozenset)):
            raise TypeError("enabled_filters must be a set.")

        unknown = config.enabled_filters - self.SUPPORTED_FILTERS

        if unknown:
            raise ValueError(
                f"Unsupported filters: {', '.join(sorted(unknown))}"
            )

        if not isinstance(config.stop_on_first_failure, bool):
            raise ValueError("stop_on_first_failure must be a boolean.")

        timeout = config.language_detection_timeout

        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout <= 0
        ):
            raise ValueError(
                "language_detection_timeout must be positive."
            )

    @staticmethod
    def _content(context: MessageFilterContext) -> str:
        """Combine message text and caption for content filtering."""
        if context.text and context.caption:
            return f"{context.text}\n{context.caption}"

        return context.text or context.caption

    def _check(
        self,
        name: str,
        matched: bool,
        reason: str,
        details: Any | None = None,
    ) -> FilterCheckResult:
        return FilterCheckResult(
            name=name,
            matched=matched,
            reason=reason,
            details=details,
        )

    async def _evaluate_language(
        self,
        content: str,
        config: LanguageFilterConfig,
        timeout: float,
        supplied_detection: LanguageDetection | None,
    ):
        if supplied_detection is not None:
            return self.language_filter.matches(
                supplied_detection,
                config,
            )

        if self.language_detector is None:
            raise RuntimeError(
                "Language filtering is enabled but no language "
                "detector is configured."
            )

        return await asyncio.wait_for(
            self.language_filter.evaluate(
                content,
                config,
                self.language_detector,
            ),
            timeout=timeout,
        )

    async def evaluate(
        self,
        context: MessageFilterContext,
        config: MessageFilterConfig,
    ) -> MessageFilterResult:
        """Run all enabled filters and return a consolidated decision."""
        self._validate_context(context)
        self._validate_config(config)

        checks: list[FilterCheckResult] = []
        failed: list[str] = []

        content = self._content(context)

        def record(result: FilterCheckResult) -> bool:
            checks.append(result)

            if not result.matched:
                failed.append(result.name)

            return result.matched

        async def should_continue() -> bool:
            return not (
                config.stop_on_first_failure and failed
            )

        for name in (
            "text",
            "media",
            "sender",
            "chat",
            "date",
            "length",
            "links",
            "hashtags",
            "keywords",
            "entities",
            "language",
            "advanced",
        ):
            if name not in config.enabled_filters:
                continue

            if not await should_continue():
                break

            try:
                if name == "text":
                    if config.text_filter is None:
                        raise ValueError("Text filter configuration is missing.")

                    result = self.text_filter.matches(
                        content,
                        config.text_filter,
                    )

                elif name == "media":
                    if config.media_filter is None:
                        raise ValueError("Media filter configuration is missing.")

                    result = self.media_filter.matches(
                        context.media,
                        config.media_filter,
                    )

                elif name == "sender":
                    if config.sender_filter is None or context.sender is None:
                        raise ValueError(
                            "Sender filter configuration or context is missing."
                        )

                    result = self.sender_filter.matches(
                        context.sender,
                        config.sender_filter,
                    )

                elif name == "chat":
                    if config.chat_filter is None or context.chat is None:
                        raise ValueError(
                            "Chat filter configuration or context is missing."
                        )

                    result = self.chat_filter.matches(
                        context.chat,
                        config.chat_filter,
                    )

                elif name == "date":
                    if config.date_filter is None or context.message_date is None:
                        raise ValueError(
                            "Date filter configuration or message date is missing."
                        )

                    result = self.date_filter.matches(
                        context.message_date,
                        config.date_filter,
                    )

                elif name == "length":
                    if config.length_filter is None:
                        raise ValueError("Length filter configuration is missing.")

                    result = self.length_filter.matches(
                        context.text,
                        config.length_filter,
                        caption=context.caption,
                    )

                elif name == "links":
                    if config.link_filter is None:
                        raise ValueError("Link filter configuration is missing.")

                    result = self.link_filter.matches(
                        content,
                        config.link_filter,
                    )

                elif name == "hashtags":
                    if config.hashtag_filter is None:
                        raise ValueError("Hashtag filter configuration is missing.")

                    result = self.hashtag_filter.matches(
                        content,
                        config.hashtag_filter,
                    )

                elif name == "keywords":
                    if config.keyword_filter is None:
                        raise ValueError("Keyword filter configuration is missing.")

                    result = self.keyword_filter.matches(
                        content,
                        config.keyword_filter,
                    )

                elif name == "entities":
                    if config.entity_filter is None:
                        raise ValueError("Entity filter configuration is missing.")

                    result = self.entity_filter.matches(
                        context.entities,
                        config.entity_filter,
                    )

                elif name == "language":
                    if config.language_filter is None:
                        raise ValueError(
                            "Language filter configuration is missing."
                        )

                    result = await self._evaluate_language(
                        content,
                        config.language_filter,
                        config.language_detection_timeout,
                        context.language_detection,
                    )

                elif name == "advanced":
                    advanced_context = FilterContext(
                        text=content,
                        message_id=context.message_id,
                        account_id=context.account_id,
                        sender_id=(
                            context.sender.sender_id
                            if context.sender
                            else None
                        ),
                        chat_id=(
                            context.chat.chat_id
                            if context.chat
                            else None
                        ),
                        date=context.message_date,
                        metadata=context.metadata,
                    )

                    result = self.advanced_filter.evaluate(
                        advanced_context,
                        config.text_filter,
                    )

                else:
                    continue

                record(
                    self._check(
                        name=name,
                        matched=result.matched,
                        reason=getattr(
                            result,
                            "reason",
                            "Filter evaluation completed.",
                        ) or "Filter evaluation completed.",
                        details=result,
                    )
                )

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                logger.exception(
                    "Message filtering failed",
                    extra={
                        "message_id": context.message_id,
                        "account_id": context.account_id,
                        "filter": name,
                    },
                )

                record(
                    self._check(
                        name=name,
                        matched=False,
                        reason=f"Filter evaluation error: {type(exc).__name__}.",
                    )
                )

        matched = not failed

        if matched:
            reason = "Message passed all enabled filters."
        else:
            reason = (
                "Message rejected by filters: "
                + ", ".join(failed)
            )

        return MessageFilterResult(
            matched=matched,
            message_id=context.message_id,
            account_id=context.account_id,
            checks=tuple(checks),
            failed_filters=tuple(failed),
            reason=reason,
        )
