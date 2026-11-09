
"""
TeleForward Telegram account schemas.

Defines:
- Telegram account creation and update requests.
- Account connection states.
- Account response and listing schemas.
- Account health information.

Security:
- Never expose Telegram session strings or authentication credentials.
- Telegram API credentials are application-level configuration,
  not per-account fields.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class TelegramAccountStatusSchema(StrEnum):
    """Telegram account connection states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AWAITING_CODE = "awaiting_code"
    AWAITING_PASSWORD = "awaiting_password"
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"


class TelegramAccountCreateRequest(RequestSchema):
    """Register a Telegram account."""

    phone_number: str = Field(
        min_length=5,
        max_length=32,
    )

    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
    )

    enabled: bool = True


class TelegramAccountUpdateRequest(RequestSchema):
    """Update Telegram account settings."""

    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
    )

    enabled: bool | None = None


class TelegramAccountListQuery(RequestSchema):
    """Filter Telegram accounts."""

    status: TelegramAccountStatusSchema | None = None

    enabled: bool | None = None

    search: str | None = Field(
        default=None,
        max_length=150,
    )


class TelegramAccountResponse(ResponseSchema):
    """Telegram account information safe for API responses."""

    id: int

    phone_number: str

    display_name: str | None = None

    telegram_user_id: int | None = None

    telegram_username: str | None = None

    first_name: str | None = None
    last_name: str | None = None

    status: TelegramAccountStatusSchema

    enabled: bool

    connected_at: datetime | None = None
    last_active_at: datetime | None = None

    last_error: str | None = None

    created_at: datetime
    updated_at: datetime


class TelegramAccountListResponse(ResponseSchema):
    """Collection of Telegram accounts."""

    accounts: list[TelegramAccountResponse] = Field(
        default_factory=list,
    )

    total: int = Field(
        ge=0,
    )


class TelegramAccountHealthResponse(ResponseSchema):
    """Operational health information for a Telegram account."""

    account_id: int

    status: TelegramAccountStatusSchema

    enabled: bool

    client_running: bool

    authorised: bool

    last_successful_check: datetime | None = None

    last_active_at: datetime | None = None

    last_error: str | None = None


class TelegramAccountOperationResponse(ResponseSchema):
    """Result of an account-level operation."""

    account_id: int

    success: bool

    status: TelegramAccountStatusSchema

    message: str
