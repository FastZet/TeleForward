"""
TeleForward message filtering engine.

Supports:
- Text, sender, chat and media filtering.
- Equality and comparison operators.
- Keyword and substring matching.
- Regular-expression matching.
- Inclusion and exclusion conditions.
- AND/OR condition groups.
- Case-sensitive and case-insensitive matching.
- Structured filtering results.

The engine is independent of SQLAlchemy and Telegram client instances.
"""

from __future__ import annotations

import operator
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence


MAX_REGEX_LENGTH = 512
MAX_TEXT_LENGTH = 100_000


class FilterOperator(StrEnum):
    """Supported filter operators."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"

    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"

    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"

    REGEX = "regex"
    NOT_REGEX = "not_regex"

    IN = "in"
    NOT_IN = "not_in"

    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"

    EXISTS = "exists"
    NOT_EXISTS = "not_exists"

    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"


class FilterLogic(StrEnum):
    """Logical combination of multiple conditions."""

    AND = "and"
    OR = "or"


@dataclass(frozen=True, slots=True)
class FilterContext:
    """Normalised message data supplied to the filtering engine."""

    message_id: int | None = None
    account_id: int | None = None

    chat_id: int | None = None
    chat_title: str | None = None
    chat_username: str | None = None
    chat_type: str | None = None

    sender_id: int | None = None
    sender_name: str | None = None
    sender_username: str | None = None

    text: str | None = None
    caption: str | None = None

    media_type: str | None = None
    has_media: bool = False
    has_photo: bool = False
    has_video: bool = False
    has_document: bool = False
    has_audio: bool = False
    has_voice: bool = False
    has_sticker: bool = False

    is_forwarded: bool = False
    is_reply: bool = False
    is_pinned: bool = False

    date: Any = None
    entities: tuple[Any, ...] = ()

    extra: Mapping[str, Any] = field(default_factory=dict)

    def get_value(self, field_name: str) -> Any:
        """Retrieve a supported field or custom metadata value."""
        if not field_name or field_name.startswith("_"):
            raise ValueError("Invalid filter field.")

        if hasattr(self, field_name):
            return getattr(self, field_name)

        if field_name in self.extra:
            return self.extra[field_name]

        return None


@dataclass(frozen=True, slots=True)
class FilterCondition:
    """A single filtering condition."""

    field: str
    operator: FilterOperator
    value: Any = None
    case_sensitive: bool = False
    negate: bool = False
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class FilterGroup:
    """A collection of conditions combined using AND or OR."""

    conditions: tuple[FilterCondition, ...]
    logic: FilterLogic = FilterLogic.AND
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ConditionResult:
    """Evaluation result for an individual condition."""

    field: str
    operator: str
    matched: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class FilterEvaluation:
    """Complete filtering evaluation result."""

    matched: bool
    logic: FilterLogic
    evaluated_conditions: int
    matched_conditions: int
    results: tuple[ConditionResult, ...]
    skipped: bool = False
    error: str | None = None


class FilterEngine:
    """Evaluate filtering conditions against Telegram messages."""

    _COMPARISON_OPERATORS = {
        FilterOperator.GREATER_THAN: operator.gt,
        FilterOperator.GREATER_THAN_OR_EQUAL: operator.ge,
        FilterOperator.LESS_THAN: operator.lt,
        FilterOperator.LESS_THAN_OR_EQUAL: operator.le,
    }

    def evaluate(
        self,
        context: FilterContext,
        conditions: Sequence[FilterCondition],
        *,
        logic: FilterLogic = FilterLogic.AND,
    ) -> FilterEvaluation:
        """Evaluate multiple conditions using AND or OR logic."""
        active_conditions = [
            condition
            for condition in conditions
            if condition.enabled
        ]

        if not active_conditions:
            return FilterEvaluation(
                matched=True,
                logic=logic,
                evaluated_conditions=0,
                matched_conditions=0,
                results=(),
                skipped=True,
            )

        results = tuple(
            self.evaluate_condition(context, condition)
            for condition in active_conditions
        )

        matched_count = sum(
            result.matched
            for result in results
        )

        if logic == FilterLogic.AND:
            matched = matched_count == len(results)
        elif logic == FilterLogic.OR:
            matched = matched_count > 0
        else:
            raise ValueError(
                f"Unsupported filter logic: {logic}"
            )

        return FilterEvaluation(
            matched=matched,
            logic=logic,
            evaluated_conditions=len(results),
            matched_conditions=matched_count,
            results=results,
        )

    def evaluate_group(
        self,
        context: FilterContext,
        group: FilterGroup,
    ) -> FilterEvaluation:
        """Evaluate a filter group."""
        if not group.enabled:
            return FilterEvaluation(
                matched=True,
                logic=group.logic,
                evaluated_conditions=0,
                matched_conditions=0,
                results=(),
                skipped=True,
            )

        return self.evaluate(
            context,
            group.conditions,
            logic=group.logic,
        )

    def evaluate_condition(
        self,
        context: FilterContext,
        condition: FilterCondition,
    ) -> ConditionResult:
        """Evaluate an individual condition."""
        try:
            actual = context.get_value(condition.field)

            matched = self._match(
                actual=actual,
                expected=condition.value,
                filter_operator=condition.operator,
                case_sensitive=condition.case_sensitive,
            )

            if condition.negate:
                matched = not matched

            return ConditionResult(
                field=condition.field,
                operator=condition.operator.value,
                matched=matched,
            )

        except (TypeError, ValueError, re.error) as exc:
            return ConditionResult(
                field=condition.field,
                operator=condition.operator.value,
                matched=False,
                reason=str(exc),
            )

    def _match(
        self,
        *,
        actual: Any,
        expected: Any,
        filter_operator: FilterOperator,
        case_sensitive: bool,
    ) -> bool:
        """Apply the requested comparison operator."""
        if filter_operator == FilterOperator.EXISTS:
            return actual is not None

        if filter_operator == FilterOperator.NOT_EXISTS:
            return actual is None

        if filter_operator == FilterOperator.IS_EMPTY:
            return self._is_empty(actual)

        if filter_operator == FilterOperator.IS_NOT_EMPTY:
            return not self._is_empty(actual)

        if actual is None:
            return False

        if filter_operator == FilterOperator.EQUALS:
            return self._compare(
                actual,
                expected,
                case_sensitive,
            )

        if filter_operator == FilterOperator.NOT_EQUALS:
            return not self._compare(
                actual,
                expected,
                case_sensitive,
            )

        if filter_operator in {
            FilterOperator.CONTAINS,
            FilterOperator.NOT_CONTAINS,
        }:
            matched = self._contains(
                actual,
                expected,
                case_sensitive,
            )

            return (
                not matched
                if filter_operator == FilterOperator.NOT_CONTAINS
                else matched
            )

        if filter_operator == FilterOperator.STARTS_WITH:
            return self._string_compare(
                actual,
                expected,
                case_sensitive,
                str.startswith,
            )

        if filter_operator == FilterOperator.ENDS_WITH:
            return self._string_compare(
                actual,
                expected,
                case_sensitive,
                str.endswith,
            )

        if filter_operator in {
            FilterOperator.REGEX,
            FilterOperator.NOT_REGEX,
        }:
            matched = self._regex_match(
                actual,
                expected,
                case_sensitive,
            )

            return (
                not matched
                if filter_operator == FilterOperator.NOT_REGEX
                else matched
            )

        if filter_operator in {
            FilterOperator.IN,
            FilterOperator.NOT_IN,
        }:
            if not isinstance(expected, (list, tuple, set, frozenset)):
                raise ValueError(
                    "IN and NOT_IN require a collection of values."
                )

            matched = any(
                self._compare(
                    actual,
                    item,
                    case_sensitive,
                )
                for item in expected
            )

            return (
                not matched
                if filter_operator == FilterOperator.NOT_IN
                else matched
            )

        comparison = self._COMPARISON_OPERATORS.get(
            filter_operator
        )

        if comparison is not None:
            return comparison(actual, expected)

        raise ValueError(
            f"Unsupported filter operator: {filter_operator}"
        )

    @staticmethod
    def _is_empty(value: Any) -> bool:
        """Determine whether a value is empty."""
        if value is None:
            return True

        if isinstance(value, (str, bytes, list, tuple, dict, set)):
            return len(value) == 0

        return False

    @staticmethod
    def _compare(
        actual: Any,
        expected: Any,
        case_sensitive: bool,
    ) -> bool:
        """Compare two values with optional case folding."""
        if (
            isinstance(actual, str)
            and isinstance(expected, str)
            and not case_sensitive
        ):
            return actual.casefold() == expected.casefold()

        return actual == expected

    @staticmethod
    def _contains(
        actual: Any,
        expected: Any,
        case_sensitive: bool,
    ) -> bool:
        """Perform substring or collection membership matching."""
        if isinstance(actual, str):
            if not isinstance(expected, str):
                raise ValueError(
                    "String containment requires a string value."
                )

            if not case_sensitive:
                actual = actual.casefold()
                expected = expected.casefold()

            return expected in actual

        if isinstance(actual, (list, tuple, set, frozenset)):
            return any(
                FilterEngine._compare(
                    item,
                    expected,
                    case_sensitive,
                )
                for item in actual
            )

        raise ValueError(
            "CONTAINS requires a string or collection field."
        )

    @staticmethod
    def _string_compare(
        actual: Any,
        expected: Any,
        case_sensitive: bool,
        comparison: Any,
    ) -> bool:
        """Perform a string prefix or suffix comparison."""
        if not isinstance(actual, str) or not isinstance(expected, str):
            raise ValueError(
                "String comparison requires string values."
            )

        if not case_sensitive:
            actual = actual.casefold()
            expected = expected.casefold()

        return comparison(actual, expected)

    @staticmethod
    def _regex_match(
        actual: Any,
        expected: Any,
        case_sensitive: bool,
    ) -> bool:
        """Perform a regular-expression match."""
        if not isinstance(actual, str):
            raise ValueError(
                "Regex matching requires a string field."
            )

        if not isinstance(expected, str) or not expected:
            raise ValueError(
                "A non-empty regular-expression pattern is required."
            )

        if len(expected) > MAX_REGEX_LENGTH:
            raise ValueError(
                "Regular-expression pattern is too long."
            )

        if len(actual) > MAX_TEXT_LENGTH:
            raise ValueError(
                "Text exceeds the maximum regex evaluation length."
            )

        flags = 0 if case_sensitive else re.IGNORECASE

        compiled = re.compile(expected, flags)

        return compiled.search(actual) is not None
