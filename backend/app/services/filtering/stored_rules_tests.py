"""Tests for mapping database filter rules to message decisions."""

from datetime import UTC, datetime

import pytest

from app.models.chat import TelegramChat, TelegramChatType
from app.models.filter_rule import (
    FilterMatchMode,
    FilterOperator,
    FilterRule,
    FilterType,
)
from app.models.message import Message, MessageType
from app.services.filtering.stored_rules import (
    StoredFilterRuleError,
    evaluate_stored_filters,
)


@pytest.fixture
def message_and_chat() -> tuple[Message, TelegramChat]:
    message = Message(
        telegram_account_id=1,
        source_chat_id=1,
        telegram_message_id=42,
        sender_id=777,
        message_type=MessageType.TEXT,
        text="Urgent: service is available at https://example.test",
        caption=None,
        media_metadata=None,
        telegram_date=datetime.now(UTC),
    )
    chat = TelegramChat(
        telegram_account_id=1,
        telegram_chat_id=-100123,
        title="Source channel",
        chat_type=TelegramChatType.CHANNEL,
    )
    return message, chat


def _rule(
    *,
    filter_type: FilterType,
    values: list,
    operator: FilterOperator = FilterOperator.INCLUDE,
    match_mode: FilterMatchMode = FilterMatchMode.ANY,
) -> FilterRule:
    return FilterRule(
        id=1,
        forwarding_rule_id=1,
        name="test",
        filter_type=filter_type,
        operator=operator,
        match_mode=match_mode,
        values=values,
        case_sensitive=False,
        is_enabled=True,
    )


def test_stored_keyword_rule_accepts_matching_message(
    message_and_chat: tuple[Message, TelegramChat],
) -> None:
    message, chat = message_and_chat
    result = evaluate_stored_filters(
        message,
        chat,
        [_rule(filter_type=FilterType.KEYWORD, values=["urgent"])],
    )

    assert result.accepted is True


def test_stored_exclusion_rule_rejects_matching_message(
    message_and_chat: tuple[Message, TelegramChat],
) -> None:
    message, chat = message_and_chat
    result = evaluate_stored_filters(
        message,
        chat,
        [
            _rule(
                filter_type=FilterType.HAS_LINK,
                values=[],
                operator=FilterOperator.EXCLUDE,
            )
        ],
    )

    assert result.accepted is False
    assert result.exclusion_matched is True


def test_sender_rule_accepts_integer_ids(
    message_and_chat: tuple[Message, TelegramChat],
) -> None:
    message, chat = message_and_chat
    result = evaluate_stored_filters(
        message,
        chat,
        [_rule(filter_type=FilterType.SENDER, values=[777])],
    )

    assert result.accepted is True


def test_all_keyword_mode_requires_each_value(
    message_and_chat: tuple[Message, TelegramChat],
) -> None:
    message, chat = message_and_chat
    result = evaluate_stored_filters(
        message,
        chat,
        [
            _rule(
                filter_type=FilterType.KEYWORD,
                values=["urgent", "missing"],
                match_mode=FilterMatchMode.ALL,
            )
        ],
    )

    assert result.accepted is False


def test_malformed_stored_values_fail_closed(
    message_and_chat: tuple[Message, TelegramChat],
) -> None:
    message, chat = message_and_chat
    with pytest.raises(StoredFilterRuleError):
        evaluate_stored_filters(
            message,
            chat,
            [_rule(filter_type=FilterType.REGEX, values=[None])],
        )

