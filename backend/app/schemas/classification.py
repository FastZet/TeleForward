
"""
TeleForward message classification schemas.

Defines:
- Classification methods and statuses.
- Classification labels.
- Classification rule creation and updates.
- Classification results.
- Classification filtering parameters.
"""

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class ClassificationMethodSchema(StrEnum):
    """Supported message classification methods."""

    KEYWORD = "keyword"
    REGEX = "regex"
    SENDER = "sender"
    CHAT = "chat"
    MESSAGE_TYPE = "message_type"
    MEDIA_TYPE = "media_type"
    COMBINED = "combined"


class ClassificationMatchModeSchema(StrEnum):
    """How multiple classification conditions are evaluated."""

    ANY = "any"
    ALL = "all"


class ClassificationStatusSchema(StrEnum):
    """Classification rule lifecycle states."""

    ACTIVE = "active"
    DISABLED = "disabled"


class ClassificationLabelCreateRequest(RequestSchema):
    """Create a classification label."""

    name: str = Field(
        min_length=1,
        max_length=100,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    color: str = Field(
        default="#64748b",
        pattern=r"^#[0-9A-Fa-f]{6}$",
    )


class ClassificationLabelUpdateRequest(RequestSchema):
    """Update a classification label."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    color: str | None = Field(
        default=None,
        pattern=r"^#[0-9A-Fa-f]{6}$",
    )


class ClassificationLabelResponse(ResponseSchema):
    """Classification label representation."""

    id: int

    name: str
    description: str | None = None

    color: str

    created_at: Any
    updated_at: Any


class ClassificationRuleCreateRequest(RequestSchema):
    """Create a message classification rule."""

    name: str = Field(
        min_length=1,
        max_length=150,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    method: ClassificationMethodSchema

    match_mode: ClassificationMatchModeSchema = (
        ClassificationMatchModeSchema.ANY
    )

    conditions: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=50,
    )

    label_ids: list[int] = Field(
        default_factory=list,
    )

    priority: int = 0

    stop_processing_on_match: bool = False

    enabled: bool = True

    @model_validator(mode="after")
    def validate_rule_conditions(self):
        """Validate the structure of classification conditions."""

        if any(label_id <= 0 for label_id in self.label_ids):
            raise ValueError("label_ids must contain positive IDs")

        if len(set(self.label_ids)) != len(self.label_ids):
            raise ValueError("label_ids must not contain duplicates")

        for condition in self.conditions:
            if not isinstance(condition, dict):
                raise ValueError("Each condition must be an object")

            if not condition:
                raise ValueError("Conditions cannot be empty")

        return self


class ClassificationRuleUpdateRequest(RequestSchema):
    """Update an existing classification rule."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    method: ClassificationMethodSchema | None = None

    match_mode: ClassificationMatchModeSchema | None = None

    conditions: list[dict[str, Any]] | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )

    label_ids: list[int] | None = None

    priority: int | None = None

    stop_processing_on_match: bool | None = None

    enabled: bool | None = None


class ClassificationRuleResponse(ResponseSchema):
    """Classification rule representation."""

    id: int

    name: str
    description: str | None = None

    method: ClassificationMethodSchema

    match_mode: ClassificationMatchModeSchema

    conditions: list[dict[str, Any]]

    label_ids: list[int]

    priority: int

    stop_processing_on_match: bool

    enabled: bool

    created_at: Any
    updated_at: Any


class ClassificationResultResponse(ResponseSchema):
    """Result of classifying a Telegram message."""

    message_id: int

    matched: bool

    matched_rule_ids: list[int] = Field(
        default_factory=list,
    )

    applied_label_ids: list[int] = Field(
        default_factory=list,
    )

    classification_details: dict[str, Any] = Field(
        default_factory=dict,
    )


class ClassificationRuleListQuery(RequestSchema):
    """Filtering parameters for classification rules."""

    method: ClassificationMethodSchema | None = None

    enabled: bool | None = None

    label_id: int | None = Field(
        default=None,
        gt=0,
    )

    search: str | None = Field(
        default=None,
        max_length=500,
    )


class ClassificationLabelListQuery(RequestSchema):
    """Filtering parameters for classification labels."""

    search: str | None = Field(
        default=None,
        max_length=500,
    )
