"""Adapt persisted forwarding filters to the pure filtering engine."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.models.chat import TelegramChat
from app.models.filter_rule import FilterMatchMode, FilterOperator, FilterRule, FilterType
from app.models.message import Message, MessageType
from app.services.filtering.engine import (
    FilterCondition,
    FilterContext,
    FilterGroup,
    FilterLogic,
    FilterOperator as EngineOperator,
)
from app.services.filtering.matcher import FilterMatcher, MatchDecision

_URL_PATTERN = re.compile(r"(?:https?://|www\.|t\.me/|telegram\.me/)", re.IGNORECASE)
_TEXT_FILTERS = frozenset({FilterType.KEYWORD, FilterType.REGEX})
_MEDIA_MESSAGE_TYPES = frozenset(
    {
        MessageType.PHOTO,
        MessageType.VIDEO,
        MessageType.DOCUMENT,
        MessageType.AUDIO,
        MessageType.VOICE,
        MessageType.VIDEO_NOTE,
        MessageType.ANIMATION,
        MessageType.STICKER,
    }
)


class StoredFilterRuleError(ValueError):
    """Raised when a persisted filter cannot be evaluated safely."""


def _rule_values(rule: FilterRule) -> list[Any]:
    values = rule.values
    if not isinstance(values, list) or not values or len(values) > 100:
        raise StoredFilterRuleError(
            f"Filter {rule.id} must contain between 1 and 100 values"
        )
    return values


def _string_values(rule: FilterRule) -> list[str]:
    values = _rule_values(rule)
    if any(not isinstance(value, str) or not value for value in values):
        raise StoredFilterRuleError(
            f"Filter {rule.id} values must be non-empty strings"
        )
    return values


def _build_group(rule: FilterRule) -> FilterGroup:
    try:
        filter_type = FilterType(rule.filter_type)
        match_mode = FilterMatchMode(rule.match_mode)
        operator = FilterOperator(rule.operator)
    except (TypeError, ValueError) as exc:
        raise StoredFilterRuleError(
            f"Filter {rule.id} has an unsupported type or mode"
        ) from exc

    case_sensitive = bool(rule.case_sensitive)
    conditions: list[FilterCondition] = []
    if filter_type in _TEXT_FILTERS:
        values = _string_values(rule)
        condition_operator = (
            EngineOperator.CONTAINS
            if filter_type == FilterType.KEYWORD
            else EngineOperator.REGEX
        )
        conditions.extend(
            FilterCondition(
                field="text",
                operator=condition_operator,
                value=value,
                case_sensitive=case_sensitive,
            )
            for value in values
        )
    elif filter_type in {
        FilterType.SENDER,
        FilterType.MEDIA_TYPE,
        FilterType.MESSAGE_TYPE,
    }:
        field_name = {
            FilterType.SENDER: "sender_id",
            FilterType.MEDIA_TYPE: "media_type",
            FilterType.MESSAGE_TYPE: "message_type",
        }[filter_type]
        values = (
            _rule_values(rule)
            if filter_type == FilterType.SENDER
            else _string_values(rule)
        )
        for value in values:
            if filter_type == FilterType.SENDER:
                if isinstance(value, bool) or not isinstance(value, (int, str)):
                    raise StoredFilterRuleError(
                        f"Filter {rule.id} sender IDs must be integers"
                    )
                try:
                    normalized: Any = int(value)
                except ValueError as exc:
                    raise StoredFilterRuleError(
                        f"Filter {rule.id} sender IDs must be integers"
                    ) from exc
            else:
                normalized = value.strip().lower()
                if not normalized:
                    raise StoredFilterRuleError(
                        f"Filter {rule.id} values cannot be blank"
                    )
            conditions.append(
                FilterCondition(
                    field=field_name,
                    operator=EngineOperator.EQUALS,
                    value=normalized,
                    case_sensitive=case_sensitive,
                )
            )
    elif filter_type in {
        FilterType.HAS_LINK,
        FilterType.HAS_TEXT,
        FilterType.HAS_MEDIA,
    }:
        if rule.values:
            raise StoredFilterRuleError(
                f"Filter {rule.id} type {filter_type.value} accepts no values"
            )
        field_name = {
            FilterType.HAS_LINK: "has_link",
            FilterType.HAS_TEXT: "has_text",
            FilterType.HAS_MEDIA: "has_media",
        }[filter_type]
        conditions.append(
            FilterCondition(
                field=field_name,
                operator=EngineOperator.EQUALS,
                value=True,
            )
        )
    else:  # pragma: no cover - enum exhaustiveness guard
        raise StoredFilterRuleError(
            f"Filter {rule.id} type {filter_type.value} is unsupported"
        )

    return FilterGroup(
        conditions=tuple(conditions),
        logic=(
            FilterLogic.AND
            if match_mode == FilterMatchMode.ALL
            else FilterLogic.OR
        ),
    )


def build_message_filter_context(
    message: Message,
    source_chat: TelegramChat,
) -> FilterContext:
    """Create the engine context from persisted message/chat metadata."""
    text = "\n".join(
        value
        for value in (message.text, message.caption)
        if isinstance(value, str) and value
    )
    metadata = message.media_metadata
    if metadata is not None and not isinstance(metadata, Mapping):
        raise StoredFilterRuleError("Message media metadata is invalid")
    media_metadata = metadata or {}
    raw_media_type = (
        media_metadata.get("media_type")
        or media_metadata.get("type")
    )
    if raw_media_type is not None and not isinstance(raw_media_type, str):
        raise StoredFilterRuleError("Message media type metadata is invalid")

    message_type = MessageType(message.message_type)
    media_type = (
        raw_media_type.strip().lower()
        if raw_media_type
        else message_type.value
        if message_type in _MEDIA_MESSAGE_TYPES
        else None
    )
    has_media = bool(media_type) or message_type in _MEDIA_MESSAGE_TYPES
    has_link = bool(_URL_PATTERN.search(text))
    chat_type = getattr(source_chat.chat_type, "value", source_chat.chat_type)

    return FilterContext(
        message_id=message.telegram_message_id,
        account_id=source_chat.telegram_account_id,
        chat_id=source_chat.telegram_chat_id,
        chat_title=source_chat.title,
        chat_username=source_chat.username,
        chat_type=str(chat_type),
        sender_id=message.sender_id,
        text=text,
        caption=message.caption,
        media_type=media_type,
        has_media=has_media,
        has_text=bool(text.strip()),
        has_link=has_link,
        date=message.telegram_date,
    )


def evaluate_stored_filters(
    message: Message,
    source_chat: TelegramChat,
    rules: Iterable[FilterRule],
    *,
    matcher: FilterMatcher | None = None,
) -> MatchDecision:
    """Evaluate enabled persisted inclusion and exclusion filters.

    Inclusion groups use the matcher’s documented OR-across-groups policy;
    each rule combines its own values according to ``match_mode``.
    Exclusion groups reject a message when any rule matches.
    """
    include_groups: list[FilterGroup] = []
    exclude_groups: list[FilterGroup] = []
    for rule in rules:
        if not rule.is_enabled:
            continue
        group = _build_group(rule)
        try:
            operator = FilterOperator(rule.operator)
        except (TypeError, ValueError) as exc:
            raise StoredFilterRuleError(
                f"Filter {rule.id} has an unsupported operator"
            ) from exc
        (include_groups if operator == FilterOperator.INCLUDE else exclude_groups).append(group)

    return (matcher or FilterMatcher()).match(
        build_message_filter_context(message, source_chat),
        include_groups=tuple(include_groups),
        exclude_groups=tuple(exclude_groups),
    )

