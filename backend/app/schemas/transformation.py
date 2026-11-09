
"""
TeleForward message transformation schemas.

Defines:
- Transformation operation types.
- Transformation rule creation and updates.
- Transformation execution settings.
- Transformation results.
- Transformation listing filters.
"""

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class TransformationTypeSchema(StrEnum):
    """Supported message transformation operations."""

    FIND_REPLACE = "find_replace"
    REGEX_REPLACE = "regex_replace"
    PREFIX = "prefix"
    SUFFIX = "suffix"
    REMOVE_TEXT = "remove_text"
    NORMALIZE_WHITESPACE = "normalize_whitespace"
    UPPERCASE = "uppercase"
    LOWERCASE = "lowercase"
    TITLE_CASE = "title_case"
    TRIM = "trim"


class TransformationScopeSchema(StrEnum):
    """Content areas affected by a transformation."""

    TEXT = "text"
    CAPTION = "caption"
    BOTH = "both"


class TransformationRuleCreateRequest(RequestSchema):
    """Create a message transformation rule."""

    name: str = Field(
        min_length=1,
        max_length=150,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    transformation_type: TransformationTypeSchema

    scope: TransformationScopeSchema = (
        TransformationScopeSchema.BOTH
    )

    search_text: str | None = Field(
        default=None,
        max_length=10000,
    )

    replacement_text: str | None = Field(
        default=None,
        max_length=10000,
    )

    regex_pattern: str | None = Field(
        default=None,
        max_length=2000,
    )

    case_sensitive: bool = True

    priority: int = 0

    enabled: bool = True

    @model_validator(mode="after")
    def validate_transformation_configuration(self):
        """Validate operation-specific parameters."""

        if self.transformation_type == TransformationTypeSchema.FIND_REPLACE:
            if self.search_text is None:
                raise ValueError(
                    "search_text is required for find_replace"
                )

            if self.replacement_text is None:
                raise ValueError(
                    "replacement_text is required for find_replace"
                )

        elif self.transformation_type == TransformationTypeSchema.REGEX_REPLACE:
            if not self.regex_pattern:
                raise ValueError(
                    "regex_pattern is required for regex_replace"
                )

            if self.replacement_text is None:
                raise ValueError(
                    "replacement_text is required for regex_replace"
                )

        elif self.transformation_type == TransformationTypeSchema.REMOVE_TEXT:
            if self.search_text is None:
                raise ValueError(
                    "search_text is required for remove_text"
                )

        elif self.transformation_type in (
            TransformationTypeSchema.PREFIX,
            TransformationTypeSchema.SUFFIX,
        ):
            if self.replacement_text is None:
                raise ValueError(
                    "replacement_text is required for prefix/suffix"
                )

        if self.transformation_type != TransformationTypeSchema.FIND_REPLACE:
            if self.search_text is not None and (
                self.transformation_type
                not in (
                    TransformationTypeSchema.REMOVE_TEXT,
                )
            ):
                raise ValueError(
                    "search_text is not valid for this transformation"
                )

        if self.transformation_type != TransformationTypeSchema.REGEX_REPLACE:
            if self.regex_pattern is not None:
                raise ValueError(
                    "regex_pattern is only valid for regex_replace"
                )

        if self.transformation_type not in (
            TransformationTypeSchema.FIND_REPLACE,
            TransformationTypeSchema.REGEX_REPLACE,
            TransformationTypeSchema.PREFIX,
            TransformationTypeSchema.SUFFIX,
        ):
            if self.replacement_text is not None:
                raise ValueError(
                    "replacement_text is not valid for this transformation"
                )

        return self


class TransformationRuleUpdateRequest(RequestSchema):
    """Update an existing transformation rule."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    transformation_type: TransformationTypeSchema | None = None

    scope: TransformationScopeSchema | None = None

    search_text: str | None = Field(
        default=None,
        max_length=10000,
    )

    replacement_text: str | None = Field(
        default=None,
        max_length=10000,
    )

    regex_pattern: str | None = Field(
        default=None,
        max_length=2000,
    )

    case_sensitive: bool | None = None

    priority: int | None = None

    enabled: bool | None = None


class TransformationRuleResponse(ResponseSchema):
    """Transformation rule representation."""

    id: int

    name: str
    description: str | None = None

    transformation_type: TransformationTypeSchema

    scope: TransformationScopeSchema

    search_text: str | None = None
    replacement_text: str | None = None
    regex_pattern: str | None = None

    case_sensitive: bool

    priority: int
    enabled: bool

    created_at: Any
    updated_at: Any


class TransformationRuleListQuery(RequestSchema):
    """Filtering parameters for transformation rules."""

    transformation_type: TransformationTypeSchema | None = None

    scope: TransformationScopeSchema | None = None

    enabled: bool | None = None

    search: str | None = Field(
        default=None,
        max_length=500,
    )


class TransformationPreviewRequest(RequestSchema):
    """Preview transformations against supplied message content."""

    text: str | None = Field(
        default=None,
        max_length=100000,
    )

    caption: str | None = Field(
        default=None,
        max_length=100000,
    )

    rule_ids: list[int] = Field(
        min_length=1,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_content(self):
        """Require at least one content field."""

        if self.text is None and self.caption is None:
            raise ValueError(
                "At least one of text or caption must be supplied"
            )

        if any(rule_id <= 0 for rule_id in self.rule_ids):
            raise ValueError("rule_ids must contain positive IDs")

        if len(set(self.rule_ids)) != len(self.rule_ids):
            raise ValueError("rule_ids must not contain duplicates")

        return self


class TransformationPreviewResponse(ResponseSchema):
    """Result of previewing message transformations."""

    original_text: str | None = None
    transformed_text: str | None = None

    original_caption: str | None = None
    transformed_caption: str | None = None

    applied_rule_ids: list[int] = Field(
        default_factory=list,
    )

    changed: bool = False

    warnings: list[str] = Field(
        default_factory=list,
    )


class TransformationResultResponse(ResponseSchema):
    """Result of applying transformations to a stored message."""

    message_id: int

    applied_rule_ids: list[int] = Field(
        default_factory=list,
    )

    changed: bool

    transformed_text: str | None = None
    transformed_caption: str | None = None

    error: str | None = None
