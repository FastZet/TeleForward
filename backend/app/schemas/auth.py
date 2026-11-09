
"""
TeleForward authentication schemas.

Defines validated request and response models for:
- Initial administrator setup.
- User login.
- Authentication status.
- Password changes.
- Logout.
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


class InitialSetupRequest(RequestSchema):
    """Request to create the initial administrator account."""

    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_.-]+$",
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

    confirm_password: SecretStr = Field(
        min_length=12,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_password_confirmation(self):
        """Ensure both supplied passwords match."""

        if self.password.get_secret_value() != (
            self.confirm_password.get_secret_value()
        ):
            raise ValueError("Passwords do not match.")

        return self


class LoginRequest(RequestSchema):
    """Administrator login credentials."""

    username: str = Field(
        min_length=3,
        max_length=255,
    )

    password: SecretStr = Field(
        min_length=1,
        max_length=128,
    )

    remember_me: bool = False


class ChangePasswordRequest(RequestSchema):
    """Request to change the authenticated user's password."""

    current_password: SecretStr = Field(
        min_length=1,
        max_length=128,
    )

    new_password: SecretStr = Field(
        min_length=12,
        max_length=128,
    )

    confirm_password: SecretStr = Field(
        min_length=12,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_password_change(self):
        """Validate confirmation and prevent password reuse."""

        current = self.current_password.get_secret_value()
        new = self.new_password.get_secret_value()
        confirmation = self.confirm_password.get_secret_value()

        if new != confirmation:
            raise ValueError("Passwords do not match.")

        if current == new:
            raise ValueError(
                "The new password must differ from the current password."
            )

        return self


class PasswordResetRequest(RequestSchema):
    """
    Administrative password-reset request.

    This schema is intended for authenticated administrator
    workflows, not an unauthenticated public password-reset flow.
    """

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
        """Ensure both supplied passwords match."""

        if self.new_password.get_secret_value() != (
            self.confirm_password.get_secret_value()
        ):
            raise ValueError("Passwords do not match.")

        return self


class AuthenticationUserResponse(ResponseSchema):
    """Safe user information returned by authentication endpoints."""

    id: int
    username: str
    email: EmailStr
    display_name: str | None = None
    is_active: bool
    is_superuser: bool
    last_login_at: datetime | None = None


class AuthenticationResponse(ResponseSchema):
    """Successful authentication response."""

    authenticated: bool = True
    user: AuthenticationUserResponse
    expires_at: datetime


class AuthenticationStatusResponse(ResponseSchema):
    """Current authentication status."""

    authenticated: bool
    user: AuthenticationUserResponse | None = None


class LogoutResponse(ResponseSchema):
    """Logout operation result."""

    authenticated: bool = False
    message: str = "Successfully logged out."
