
"""
TeleForward Telegram profile schemas.

Defines:
- Telegram user profile information.
- Connected account identity information.
- Profile retrieval and refresh requests.
- Profile synchronization results.

Sensitive Telegram identifiers and authentication material, such as
access hashes and session credentials, must never be exposed through
these response schemas.
"""

from datetime import datetime

from pydantic import Field

from app.schemas.common import RequestSchema, ResponseSchema


class TelegramProfileRequest(RequestSchema):
    """Request to retrieve a Telegram user's profile."""

    account_id: int = Field(gt=0)

    user_id: int = Field(gt=0)

    refresh: bool = False


class TelegramProfileResponse(ResponseSchema):
    """Publicly representable Telegram user profile information."""

    account_id: int

    telegram_user_id: int

    username: str | None = Field(
        default=None,
        max_length=255,
    )

    first_name: str | None = Field(
        default=None,
        max_length=255,
    )

    last_name: str | None = Field(
        default=None,
        max_length=255,
    )

    display_name: str | None = Field(
        default=None,
        max_length=512,
    )

    phone: str | None = Field(
        default=None,
        max_length=32,
    )

    bio: str | None = Field(
        default=None,
        max_length=10000,
    )

    is_bot: bool = False

    is_verified: bool = False

    is_premium: bool = False

    is_scam: bool = False

    is_fake: bool = False

    is_deleted: bool = False

    is_contact: bool = False

    is_mutual_contact: bool = False

    has_profile_photo: bool = False

    profile_photo_id: int | None = None

    restriction_reason: str | None = Field(
        default=None,
        max_length=2000,
    )

    last_seen_at: datetime | None = None

    fetched_at: datetime


class TelegramAccountIdentityResponse(ResponseSchema):
    """Identity information for the connected Telegram account."""

    account_id: int

    telegram_user_id: int

    username: str | None = Field(
        default=None,
        max_length=255,
    )

    first_name: str | None = Field(
        default=None,
        max_length=255,
    )

    last_name: str | None = Field(
        default=None,
        max_length=255,
    )

    display_name: str | None = Field(
        default=None,
        max_length=512,
    )

    phone: str | None = Field(
        default=None,
        max_length=32,
    )

    is_bot: bool = False

    is_premium: bool = False

    is_verified: bool = False

    has_profile_photo: bool = False

    connected_at: datetime | None = None

    last_verified_at: datetime | None = None


class TelegramProfileRefreshRequest(RequestSchema):
    """Request to refresh cached Telegram profile information."""

    account_id: int = Field(gt=0)

    user_ids: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    @staticmethod
    def validate_user_ids(user_ids: list[int]) -> None:
        if any(user_id <= 0 for user_id in user_ids):
            raise ValueError(
                "All Telegram user IDs must be positive"
            )

        if len(user_ids) != len(set(user_ids)):
            raise ValueError(
                "Telegram user IDs must not contain duplicates"
            )

    def model_post_init(self, __context) -> None:
        if self.user_ids is not None:
            self.validate_user_ids(self.user_ids)


class TelegramProfileRefreshResponse(ResponseSchema):
    """Result of refreshing Telegram profile information."""

    account_id: int

    requested_count: int = Field(ge=0)

    refreshed_count: int = Field(ge=0)

    failed_count: int = Field(ge=0)

    failed_user_ids: list[int] = Field(
        default_factory=list,
    )

    started_at: datetime

    completed_at: datetime | None = None

    error_message: str | None = Field(
        default=None,
        max_length=2000,
    )
