"""
TeleForward filter rule utilities.

Responsible for:
- Constructing filter conditions from stored configurations.
- Validating condition definitions.
- Normalising filter operators and values.
- Building logical filter groups.
- Validating nested filter configurations.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.filtering.engine import (
    FilterCondition,
    FilterGroup,
    FilterLogic,
    FilterOperator,
)


MAX_CONDITIONS_PER_GROUP = 100
MAX_FILTER_GROUPS = 50
MAX_FILTER_NESTING_DEPTH = 5

SUPPORTED_FIELDS = frozenset({
    "message_id",
    "account_id",
    "chat_id",
    "chat_title",
    "chat_username",
    "chat_type",
    "sender_id",
    "sender_name",
    "sender_username",
    "text",
    "caption",
    "media_type",
    "has_media",
    "has_photo",
    "has_video",
    "has_document",
    "has_audio",
    "has_voice",
    "has_sticker",
    "is_forwarded",
    "is_reply",
    "is_pinned",
    "date",
})


class FilterRuleError(ValueError):
    """Raised when a filter rule is invalid."""


def _parse_operator(value: Any) -> FilterOperator:
    """Convert an operator value into its enum representation."""
    try:
        return FilterOperator(value)
    except (ValueError, TypeError) as exc:
        raise FilterRuleError(
            f"Unsupported filter operator: {value!r}"
        ) from exc


def _parse_logic(value: Any) -> FilterLogic:
    """Convert a logical operator into its enum representation."""
    try:
        return FilterLogic(value)
    except (ValueError, TypeError) as exc:
        raise FilterRuleError(
            f"Unsupported filter logic: {value!r}"
        ) from exc


def _validate_field(field_name: Any) -> str:
    """Validate a field against the supported filter fields."""
    if not isinstance(field_name, str) or not field_name:
        raise FilterRuleError(
            "Filter field must be a non-empty string."
        )

    if field_name not in SUPPORTED_FIELDS:
        raise FilterRuleError(
            f"Unsupported filter field: {field_name!r}"
        )

    return field_name


def _validate_boolean(
    value: Any,
    field_name: str,
) -> bool:
    """Require an actual boolean value."""
    if not isinstance(value, bool):
        raise FilterRuleError(
            f"{field_name} must be a boolean."
        )

    return value


def _validate_condition_value(
    filter_operator: FilterOperator,
    value: Any,
) -> Any:
    """Validate values according to their comparison operator."""
    no_value_operators = {
        FilterOperator.EXISTS,
        FilterOperator.NOT_EXISTS,
        FilterOperator.IS_EMPTY,
        FilterOperator.IS_NOT_EMPTY,
    }

    if filter_operator in no_value_operators:
        return None

    if value is None:
        raise FilterRuleError(
            f"Operator {filter_operator.value!r} requires a value."
        )

    if filter_operator in {
        FilterOperator.REGEX,
        FilterOperator.NOT_REGEX,
    }:
        if not isinstance(value, str) or not value:
            raise FilterRuleError(
                "Regex operators require a non-empty string."
            )

        if len(value) > 512:
            raise FilterRuleError(
                "Regex pattern exceeds the maximum length."
            )

    if filter_operator in {
        FilterOperator.IN,
        FilterOperator.NOT_IN,
    }:
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise FilterRuleError(
                "IN and NOT_IN require a collection."
            )

        if not value:
            raise FilterRuleError(
                "IN and NOT_IN collections cannot be empty."
            )

        if len(value) > 500:
            raise FilterRuleError(
                "Filter value collection is too large."
            )

    if filter_operator in {
        FilterOperator.CONTAINS,
        FilterOperator.NOT_CONTAINS,
        FilterOperator.STARTS_WITH,
        FilterOperator.ENDS_WITH,
    }:
        if not isinstance(value, str):
            raise FilterRuleError(
                f"Operator {filter_operator.value!r} requires a string."
            )

    return value


def build_condition(
    configuration: Mapping[str, Any],
) -> FilterCondition:
    """
    Build a validated filter condition from a mapping.

    Expected keys:
        field
        operator
        value
        case_sensitive
        negate
        enabled
    """
    if not isinstance(configuration, Mapping):
        raise FilterRuleError(
            "Filter condition must be a mapping."
        )

    field_name = _validate_field(
        configuration.get("field")
    )

    filter_operator = _parse_operator(
        configuration.get("operator")
    )

    value = _validate_condition_value(
        filter_operator,
        configuration.get("value"),
    )

    case_sensitive = _validate_boolean(
        configuration.get("case_sensitive", False),
        "case_sensitive",
    )

    negate = _validate_boolean(
        configuration.get("negate", False),
        "negate",
    )

    enabled = _validate_boolean(
        configuration.get("enabled", True),
        "enabled",
    )

    return FilterCondition(
        field=field_name,
        operator=filter_operator,
        value=value,
        case_sensitive=case_sensitive,
        negate=negate,
        enabled=enabled,
    )


def build_filter_group(
    configuration: Mapping[str, Any],
) -> FilterGroup:
    """
    Build a validated filter group from a mapping.

    Expected keys:
        logic
        conditions
        enabled
    """
    if not isinstance(configuration, Mapping):
        raise FilterRuleError(
            "Filter group must be a mapping."
        )

    logic = _parse_logic(
        configuration.get("logic", FilterLogic.AND.value)
    )

    raw_conditions = configuration.get("conditions", [])

    if not isinstance(raw_conditions, Sequence) or isinstance(
        raw_conditions,
        (str, bytes, bytearray),
    ):
        raise FilterRuleError(
            "Filter group conditions must be a sequence."
        )

    if len(raw_conditions) > MAX_CONDITIONS_PER_GROUP:
        raise FilterRuleError(
            "Filter group exceeds the maximum number of conditions."
        )

    enabled = _validate_boolean(
        configuration.get("enabled", True),
        "enabled",
    )

    conditions = tuple(
        build_condition(condition)
        for condition in raw_conditions
    )

    return FilterGroup(
        conditions=conditions,
        logic=logic,
        enabled=enabled,
    )


def validate_filter_configuration(
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Validate a complete flat filter configuration.

    Returns a normalised configuration dictionary.
    """
    group = build_filter_group(configuration)

    return {
        "logic": group.logic.value,
        "enabled": group.enabled,
        "conditions": [
            {
                "field": condition.field,
                "operator": condition.operator.value,
                "value": condition.value,
                "case_sensitive": condition.case_sensitive,
                "negate": condition.negate,
                "enabled": condition.enabled,
            }
            for condition in group.conditions
        ],
    }
