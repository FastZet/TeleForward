
"""
TeleForward forwarding-rule schemas.

Defines:
- Forwarding rule creation and updates.
- Forwarding mode selection.
- Rule execution controls.
- Forwarding rule response models.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class ForwardingModeSchema(StrEnum):
    """Supported message-forwarding modes."""

    FORWARD = "forward"
    COPY = "copy"


class ForwardingRuleCreateRequest(RequestSchema):
    """Request to create a Telegram forwarding rule."""

    name: str = Field(
        min_length=1,
        max_length=100,
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
    )

    telegram_account_id: int = Field(gt=0)

    source_chat_id: int = Field(gt=0)

    destination_chat_id: int = Field(gt=0)

    mode: ForwardingModeSchema = ForwardingModeSchema.COPY

    is_enabled: bool = True

    stop_on_error: bool = False

    preserve_grouped_media: bool = True

    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_chat_selection(self):
        """Prevent selecting the same internal chat record twice."""

        if self.source_chat_id == self.destination_chat_id:
            raise ValueError(
                "Source and destination chats must be different."
            )

        return self


class ForwardingRuleUpdateRequest(RequestSchema):
    """Request to update an existing forwarding rule."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
    )

    source_chat_id: int | None = Field(
        default=None,
        gt=0,
    )

    destination_chat_id: int | None = Field(
        default=None,
        gt=0,
    )

    mode: ForwardingModeSchema | None = None

    is_enabled: bool | None = None

    stop_on_error: bool | None = None

    preserve_grouped_media: bool | None = None

    settings: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_non_empty_update(self):
        """Reject requests without any update fields."""

        if not self.model_fields_set:
            raise ValueError(
                "At least one field must be provided."
            )

        return self


class ForwardingRuleControlRequest(RequestSchema):
    """Request to enable, disable or manually control a rule."""

    is_enabled: bool


class ForwardingRuleResponse(ResponseSchema):
    """Detailed forwarding rule representation."""

    id: int

    name: str
    description: str | None = None

    telegram_account_id: int
    source_chat_id: int
    destination_chat_id: int

    mode: ForwardingModeSchema

    is_enabled: bool
    stop_on_error: bool
    preserve_grouped_media: bool

    settings: dict[str, Any]

    last_run_at: datetime | None = None
    last_error: str | None = None

    created_at: datetime
    updated_at: datetime


class ForwardingRuleSummaryResponse(ResponseSchema):
    """Compact forwarding rule representation."""

    id: int
    name: str

    telegram_account_id: int
    source_chat_id: int
    destination_chat_id: int

    mode: ForwardingModeSchema
    is_enabled: bool

    last_run_at: datetime | None = None


class ForwardingRuleStatisticsResponse(ResponseSchema):
    """Aggregate forwarding statistics for a rule."""

    rule_id: int

    total_processed: int
    total_forwarded: int
    total_skipped: int
    total_failed: int

    last_run_at: datetime | None = None
