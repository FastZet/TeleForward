
"""
TeleForward Telegram session schemas.

Defines:
- Telegram login challenge requests.
- Login code and two-factor authentication requests.
- Session lifecycle operations.
- Telegram connection status responses.

Security:
- Telegram phone-code hashes and session credentials must remain
  server-side.
- Authentication challenges must be associated with the correct
  Telegram account and expire after a limited period.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, SecretStr

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


class TelegramSessionStatusSchema(StrEnum):
    """Telegram account connection states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AWAITING_CODE = "awaiting_code"
    AWAITING_PASSWORD = "awaiting_password"
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"


class TelegramChallengeTypeSchema(StrEnum):
    """Supported Telegram authentication challenges."""

    PHONE_CODE = "phone_code"
    TWO_FACTOR_PASSWORD = "two_factor_password"


class TelegramSessionStartRequest(RequestSchema):
    """Initiate Telegram authentication for an account."""

    account_id: int = Field(
        gt=0,
    )

    phone_number: str = Field(
        min_length=5,
        max_length=32,
    )


class TelegramSessionCodeRequest(RequestSchema):
    """Submit the Telegram login code."""

    account_id: int = Field(
        gt=0,
    )

    phone_code: str = Field(
        min_length=1,
        max_length=20,
    )


class TelegramSessionPasswordRequest(RequestSchema):
    """Submit a Telegram two-factor authentication password."""

    account_id: int = Field(
        gt=0,
    )

    password: SecretStr = Field(
        min_length=1,
        max_length=256,
    )


class TelegramSessionDisconnectRequest(RequestSchema):
    """Disconnect a Telegram account session."""

    account_id: int = Field(
        gt=0,
    )

    revoke_remote_session: bool = False


class TelegramSessionChallengeResponse(ResponseSchema):
    """Authentication challenge information."""

    account_id: int

    challenge_type: TelegramChallengeTypeSchema

    status: TelegramSessionStatusSchema

    expires_at: datetime | None = None

    requires_password: bool = False

    message: str | None = None


class TelegramSessionResponse(ResponseSchema):
    """Telegram session status without exposing credentials."""

    account_id: int

    status: TelegramSessionStatusSchema

    phone_number: str | None = None

    telegram_user_id: int | None = None

    telegram_username: str | None = None

    first_name: str | None = None
    last_name: str | None = None

    connected_at: datetime | None = None
    last_active_at: datetime | None = None

    expires_at: datetime | None = None

    error_message: str | None = None


class TelegramSessionListResponse(ResponseSchema):
    """Collection of Telegram session statuses."""

    sessions: list[TelegramSessionResponse] = Field(
        default_factory=list,
    )

    total: int = Field(
        ge=0,
    )


class TelegramSessionHealthResponse(ResponseSchema):
    """Operational health information for a Telegram session."""

    account_id: int

    connected: bool

    authorised: bool

    client_running: bool

    last_successful_check: datetime | None = None

    last_error: str | None = None


class TelegramSessionOperationResponse(ResponseSchema):
    """Result of a Telegram session lifecycle operation."""

    account_id: int

    success: bool

    status: TelegramSessionStatusSchema

    message: str
