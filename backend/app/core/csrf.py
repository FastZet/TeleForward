
"""
TeleForward CSRF protection utilities.

Provides secure token generation, validation and request
verification for browser-based session authentication.
"""

import secrets
from collections.abc import Iterable

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


CSRF_HEADER_NAME = "X-CSRF-Token"

SAFE_METHODS = frozenset({
    "GET",
    "HEAD",
    "OPTIONS",
    "TRACE",
})


def generate_csrf_token() -> str:
    """
    Generate a cryptographically secure CSRF token.

    Returns:
        A URL-safe random token.
    """
    return secrets.token_urlsafe(32)


def validate_csrf_token(
    submitted_token: str | None,
    session_token: str | None,
) -> bool:
    """
    Compare a submitted CSRF token against the session token.

    Constant-time comparison helps prevent timing attacks.
    """
    if not submitted_token or not session_token:
        return False

    return secrets.compare_digest(
        submitted_token,
        session_token,
    )


def get_allowed_origins() -> set[str]:
    """
    Return the configured browser origins.

    Origins are compared exactly, including scheme and port.
    """
    settings = get_settings()

    return {
        origin.rstrip("/")
        for origin in settings.cors_origins
        if origin
    }


def validate_request_origin(
    request: Request,
    additional_origins: Iterable[str] | None = None,
) -> bool:
    """
    Validate the Origin header against configured origins.

    Requests without an Origin header are rejected for
    browser-origin validation. Non-browser clients should
    authenticate through an appropriate non-cookie mechanism.
    """
    origin = request.headers.get("origin")

    if not origin:
        return False

    allowed_origins = get_allowed_origins()

    if additional_origins:
        allowed_origins.update(
            value.rstrip("/")
            for value in additional_origins
        )

    return origin.rstrip("/") in allowed_origins


async def enforce_csrf_protection(request: Request) -> None:
    """
    Enforce CSRF protection for state-changing HTTP requests.

    Safe methods are exempt. Other methods require:
    - A valid authenticated session.
    - A matching CSRF header and session token.
    - An allowed Origin header.

    The authentication layer must populate request.state.session
    with the validated session data.
    """
    if request.method.upper() in SAFE_METHODS:
        return

    session = getattr(request.state, "session", None)

    if not isinstance(session, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    session_token = session.get("csrf_token")

    submitted_token = request.headers.get(CSRF_HEADER_NAME)

    if not validate_csrf_token(
        submitted_token,
        session_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )

    if not validate_request_origin(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed.",
        )
