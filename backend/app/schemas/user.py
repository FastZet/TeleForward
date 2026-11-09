
"""
TeleForward user management schemas.

Defines:
- User creation requests.
- User profile updates.
- Administrative user updates.
- Safe user response models.
"""

from datetime import datetime

from pydantic import (
    EmailStr,
    Field,
    SecretStr,
    model_validator,
)

from app.schemas.common import (
    RequestSchema,
    ResponseSchema,
)


USERNAME_PATTERN = r"^[a-zA-Z0-9_.-]+$"


class UserCreateRequest(RequestSchema):
    """Request to create a new user account."""

    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=USERNAME_PATTERN,
    )

    email: EmailStr

    display_name: str | None = Field(
        default=None,
        max_length=100,
    )

    password: SecretStr = Field(
        min_length=12,
        max_length=128,
    )

    is_active: bool = True


class UserUpdateRequest(RequestSchema):
    """Request to update the authenticated user's profile."""

    email: EmailStr | None = None

    display_name: str | None = Field(
        default=None,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_non_empty_update(self):
        """Reject requests that contain no update fields."""

        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")

        return self


class UserAdminUpdateRequest(RequestSchema):
    """Request for an administrator to update user permissions."""

    email: EmailStr | None = None

    display_name: str | None = Field(
        default=None,
        max_length=100,
    )

    is_active: bool | None = None

    is_superuser: bool | None = None

    @model_validator(mode="after")
    def validate_non_empty_update(self):
        """Reject requests that contain no update fields."""

        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")

        return self


class UserResponse(ResponseSchema):
    """Safe user representation for API responses."""

    id: int
    username: str
    email: EmailStr
    display_name: str | None = None

    is_active: bool
    is_superuser: bool

    failed_login_attempts: int
    locked_until: datetime | None = None

    last_login_at: datetime | None = None
    password_changed_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


class UserSummaryResponse(ResponseSchema):
    """Compact user representation for administrative listings."""

    id: int
    username: str
    display_name: str | None = None
    is_active: bool
    is_superuser: bool
    created_at: datetime


class UserPasswordResetRequest(RequestSchema):
    """Administrator-initiated password reset for a user."""

    new_password: SecretStr = Field(
        min_length=12,
        max_length=128,
    )

    confirm_password: SecretStr = Field(
        min_length=12,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_password_confirmation(self):
        """Ensure the new password and confirmation match."""

        if self.new_password.get_secret_value() != (
            self.confirm_password.get_secret_value()
        ):
            raise ValueError("Passwords do not match.")

        return self
