
"""
TeleForward forwarding-delivery schemas.

Defines:
- Forwarding delivery statuses.
- Forwarded message responses.
- Forwarding delivery filters.
- Delivery operation results.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class ForwardedMessageStatusSchema(StrEnum):
    """Lifecycle states of a forwarding delivery."""

    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ForwardedMessageListQuery(RequestSchema):
    """Filtering parameters for forwarding-delivery records."""

    forwarding_rule_id: int | None = Field(
        default=None,
        gt=0,
    )

    message_id: int | None = Field(
        default=None,
        gt=0,
    )

    destination_chat_id: int | None = Field(
        default=None,
        gt=0,
    )

    status: ForwardedMessageStatusSchema | None = None

    date_from: datetime | None = None
    date_to: datetime | None = None

    search: str | None = Field(
        default=None,
        max_length=500,
    )


class ForwardedMessageResponse(ResponseSchema):
    """Detailed forwarding-delivery record."""

    id: int

    forwarding_rule_id: int
    message_id: int

    destination_chat_id: int

    telegram_message_id: int | None = None

    status: ForwardedMessageStatusSchema

    attempts: int = Field(ge=0)

    error_message: str | None = None

    forwarded_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


class ForwardedMessageSummaryResponse(ResponseSchema):
    """Compact forwarding-delivery record for listings."""

    id: int

    forwarding_rule_id: int
    message_id: int

    destination_chat_id: int

    telegram_message_id: int | None = None

    status: ForwardedMessageStatusSchema

    attempts: int = Field(ge=0)

    forwarded_at: datetime | None = None


class ForwardingDeliveryResult(ResponseSchema):
    """Result returned after attempting a forwarding operation."""

    message_id: int
    forwarding_rule_id: int
    destination_chat_id: int

    status: ForwardedMessageStatusSchema

    telegram_message_id: int | None = None

    success: bool = False

    error_message: str | None = None
