
"""
TeleForward Telegram error schemas.

Defines:
- Normalized Telegram error categories.
- Telegram API error details.
- Flood-wait information.
- Error response representations.

Raw Telethon exceptions and stack traces must never be exposed
directly through public API responses.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import ResponseSchema


class TelegramErrorCategorySchema(StrEnum):
    """Broad Telegram error categories."""

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    ACCOUNT = "account"
    CHAT = "chat"
    MESSAGE = "message"
    MEDIA = "media"
    PERMISSION = "permission"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    VALIDATION = "validation"
    SERVER = "server"
    UNKNOWN = "unknown"


class TelegramErrorCodeSchema(StrEnum):
    """Normalized Telegram error codes."""

    SESSION_EXPIRED = "session_expired"
    SESSION_REVOKED = "session_revoked"
    INVALID_SESSION = "invalid_session"
    INVALID_API_CREDENTIALS = "invalid_api_credentials"
    AUTH_KEY_UNREGISTERED = "auth_key_unregistered"
    PHONE_NUMBER_INVALID = "phone_number_invalid"
    PHONE_CODE_INVALID = "phone_code_invalid"
    PHONE_CODE_EXPIRED = "phone_code_expired"
    PASSWORD_REQUIRED = "password_required"
    PASSWORD_INVALID = "password_invalid"

    CHAT_NOT_FOUND = "chat_not_found"
    CHAT_WRITE_FORBIDDEN = "chat_write_forbidden"
    CHAT_ADMIN_REQUIRED = "chat_admin_required"
    USER_NOT_PARTICIPANT = "user_not_participant"
    USER_BANNED = "user_banned"

    MESSAGE_NOT_FOUND = "message_not_found"
    MESSAGE_ID_INVALID = "message_id_invalid"
    MESSAGE_TOO_LONG = "message_too_long"
    MESSAGE_EMPTY = "message_empty"
    MESSAGE_NOT_MODIFIED = "message_not_modified"

    MEDIA_INVALID = "media_invalid"
    MEDIA_EMPTY = "media_empty"
    MEDIA_TOO_LARGE = "media_too_large"

    FLOOD_WAIT = "flood_wait"
    SLOW_MODE_WAIT = "slow_mode_wait"
    RATE_LIMITED = "rate_limited"

    CONNECTION_ERROR = "connection_error"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"

    INVALID_REQUEST = "invalid_request"
    UNKNOWN_ERROR = "unknown_error"


class TelegramErrorDetail(ResponseSchema):
    """Normalized information about a Telegram API failure."""

    category: TelegramErrorCategorySchema

    code: TelegramErrorCodeSchema

    message: str = Field(
        max_length=2000,
    )

    retryable: bool = False

    retry_after_seconds: int | None = Field(
        default=None,
        ge=0,
    )

    telegram_error_code: int | None = None

    occurred_at: datetime


class TelegramErrorResponse(ResponseSchema):
    """Standardized API response for Telegram-related errors."""

    success: bool = False

    error: TelegramErrorDetail

    request_id: str | None = Field(
        default=None,
        max_length=128,
    )


class TelegramFloodWaitResponse(ResponseSchema):
    """Structured flood-wait information."""

    account_id: int

    wait_seconds: int = Field(
        ge=0,
    )

    retry_after: datetime

    operation: str | None = Field(
        default=None,
        max_length=255,
    )

    is_automatically_retryable: bool = True


class TelegramConnectionErrorResponse(ResponseSchema):
    """Telegram account connection failure information."""

    account_id: int

    connected: bool = False

    error: TelegramErrorDetail

    last_successful_connection: datetime | None = None

    next_retry_at: datetime | None = None
