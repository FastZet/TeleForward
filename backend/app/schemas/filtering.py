
"""
TeleForward message filtering schemas.

Defines:
- Filter types.
- Inclusion and exclusion operators.
- Matching modes.
- Filter creation and update requests.
- Filter response models.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class FilterTypeSchema(StrEnum):
    """Supported message filter categories."""

    KEYWORD = "keyword"
    REGEX = "regex"
    SENDER = "sender"
    MEDIA_TYPE = "media_type"
    MESSAGE_TYPE = "message_type"
    HAS_LINK = "has_link"
    HAS_TEXT = "has_text"
    HAS_MEDIA = "has_media"


class FilterOperatorSchema(StrEnum):
    """Determines whether matching messages are included or excluded."""

    INCLUDE = "include"
    EXCLUDE = "exclude"


class FilterMatchModeSchema(StrEnum):
    """Determines how multiple filter values are evaluated."""

    ANY = "any"
    ALL = "all"


class FilterRuleCreateRequest(RequestSchema):
    """Request to create a message filter."""

    forwarding_rule_id: int = Field(gt=0)

    name: str = Field(
        min_length=1,
        max_length=100,
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
    )

    filter_type: FilterTypeSchema

    operator: FilterOperatorSchema = FilterOperatorSchema.INCLUDE

    match_mode: FilterMatchModeSchema = FilterMatchModeSchema.ANY

    values: list[Any] = Field(
        default_factory=list,
        max_length=100,
    )

    case_sensitive: bool = False

    is_enabled: bool = True

    priority: int = Field(
        default=100,
        ge=0,
        le=10000,
    )

    @model_validator(mode="after")
    def validate_filter_values(self):
        """Validate filter values according to the selected filter type."""

        value_required_types = {
            FilterTypeSchema.KEYWORD,
            FilterTypeSchema.REGEX,
            FilterTypeSchema.SENDER,
            FilterTypeSchema.MEDIA_TYPE,
            FilterTypeSchema.MESSAGE_TYPE,
        }

        if self.filter_type in value_required_types and not self.values:
            raise ValueError(
                "At least one value is required for this filter type."
            )

        if self.filter_type in {
            FilterTypeSchema.HAS_LINK,
            FilterTypeSchema.HAS_TEXT,
            FilterTypeSchema.HAS_MEDIA,
        } and self.values:
            raise ValueError(
                "This filter type does not accept values."
            )

        if self.filter_type == FilterTypeSchema.REGEX:
            if not all(
                isinstance(value, str) and value.strip()
                for value in self.values
            ):
                raise ValueError(
                    "Regex filters require non-empty string patterns."
                )

        return self


class FilterRuleUpdateRequest(RequestSchema):
    """Request to update an existing message filter."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
    )

    filter_type: FilterTypeSchema | None = None

    operator: FilterOperatorSchema | None = None

    match_mode: FilterMatchModeSchema | None = None

    values: list[Any] | None = Field(
        default=None,
        max_length=100,
    )

    case_sensitive: bool | None = None

    is_enabled: bool | None = None

    priority: int | None = Field(
        default=None,
        ge=0,
        le=10000,
    )

    @model_validator(mode="after")
    def validate_non_empty_update(self):
        """Reject requests without any update fields."""

        if not self.model_fields_set:
            raise ValueError(
                "At least one field must be provided."
            )

        return self


class FilterRuleResponse(ResponseSchema):
    """Detailed message filter representation."""

    id: int
    forwarding_rule_id: int

    name: str
    description: str | None = None

    filter_type: FilterTypeSchema
    operator: FilterOperatorSchema
    match_mode: FilterMatchModeSchema

    values: list[Any]

    case_sensitive: bool
    is_enabled: bool
    priority: int

    created_at: datetime
    updated_at: datetime


class FilterRuleSummaryResponse(ResponseSchema):
    """Compact filter representation."""

    id: int
    forwarding_rule_id: int

    name: str
    filter_type: FilterTypeSchema

    operator: FilterOperatorSchema
    is_enabled: bool
    priority: int
