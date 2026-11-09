
"""
TeleForward Telegram account schemas.

Defines:
- Telegram account creation and updates.
- Telegram authentication requests.
- Login-code and two-step verification requests.
- Account connection and status responses.
"""

from datetime import datetime

from pydantic import (
    Field,
    SecretStr,
)

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class TelegramAccountCreateRequest(RequestSchema):
    """Request to register a Telegram account."""

    name: str = Field(
        min_length=1,
        max_length=100,
    )

    phone_number: str = Field(
        min_length=5,
        max_length=20,
        pattern=r"^\+[1-9]\d{4,14}$",
    )

    is_primary: bool = False


class TelegramAccountUpdateRequest(RequestSchema):
    """Request to update Telegram account settings."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    is_enabled: bool | None = None

    is_primary: bool | None = None


class TelegramAuthenticationStartRequest(RequestSchema):
    """Request to initiate Telegram phone-number authentication."""

    phone_number: str = Field(
        min_length=5,
        max_length=20,
        pattern=r"^\+[1-9]\d{4,14}$",
    )


class TelegramLoginCodeRequest(RequestSchema):
    """Request to submit the Telegram login verification code."""

    account_id: int = Field(gt=0)

    phone_code: SecretStr = Field(
        min_length=3,
        max_length=12,
    )

    phone_code_hash: SecretStr = Field(
        min_length=1,
        max_length=512,
    )


class TelegramTwoStepVerificationRequest(RequestSchema):
    """Request to submit a Telegram two-step verification password."""

    account_id: int = Field(gt=0)

    password: SecretStr = Field(
        min_length=1,
        max_length=256,
    )


class TelegramAuthenticationResponse(ResponseSchema):
    """Result of a Telegram authentication operation."""

    account_id: int
    status: str
    requires_code: bool = False
    requires_password: bool = False
    message: str | None = None


class TelegramAccountResponse(ResponseSchema):
    """Safe Telegram account representation."""

    id: int
    name: str
    phone_number: str

    telegram_user_id: int | None = None
    telegram_username: str | None = None

    first_name: str | None = None
    last_name: str | None = None

    status: str
    is_enabled: bool
    is_primary: bool

    last_connected_at: datetime | None = None
    last_authenticated_at: datetime | None = None
    last_error: str | None = None

    created_at: datetime
    updated_at: datetime


class TelegramAccountSummaryResponse(ResponseSchema):
    """Compact Telegram account representation."""

    id: int
    name: str
    phone_number: str
    telegram_username: str | None = None
    status: str
    is_enabled: bool
    is_primary: bool
    last_connected_at: datetime | None = None


class TelegramConnectionStatusResponse(ResponseSchema):
    """Current Telegram connection status."""

    account_id: int
    connected: bool
    authenticated: bool
    status: str
    checked_at: datetime
