
"""
TeleForward CSRF protection.

Implements signed double-submit cookie CSRF protection for
browser-facing requests.

Authentication endpoints and other explicitly configured
exempt paths should be reviewed carefully before use.
"""

import hashlib
import hmac
import secrets
from typing import Iterable
from urllib.parse import urlparse

from fastapi import Request
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings


CSRF_COOKIE_NAME = "teleforward_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

SAFE_METHODS = frozenset({
    "GET",
    "HEAD",
    "OPTIONS",
    "TRACE",
})

DEFAULT_EXEMPT_PATHS = frozenset({
    "/health",
    "/health/live",
    "/health/ready",
    "/health/details",
    "/health/application",
})


def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token."""
    return secrets.token_urlsafe(32)


def _get_signing_key() -> bytes:
    """Get the persistent application secret used for CSRF signing."""
    settings = get_settings()

    secret = getattr(settings, "secret_key", None)

    if not secret:
        raise RuntimeError(
            "Application secret key is not configured"
        )

    return secret.encode("utf-8")


def _sign_token(token: str) -> str:
    """Generate a keyed HMAC-SHA256 signature."""
    return hmac.new(
        _get_signing_key(),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_signed_csrf_token() -> str:
    """Create a token containing its HMAC signature."""
    token = generate_csrf_token()
    signature = _sign_token(token)

    return f"{token}.{signature}"


def validate_csrf_token(token: str | None) -> bool:
    """
    Validate token structure and HMAC signature.

    Returns False for malformed or tampered tokens.
    """
    if not token or "." not in token:
        return False

    try:
        random_value, supplied_signature = token.rsplit(".", 1)

        if not random_value or not supplied_signature:
            return False

        expected_signature = _sign_token(random_value)

        return hmac.compare_digest(
            supplied_signature,
            expected_signature,
        )

    except (RuntimeError, ValueError, TypeError):
        return False


def validate_csrf_pair(
    cookie_token: str | None,
    header_token: str | None,
) -> bool:
    """Validate the signed cookie and request header together."""
    if not cookie_token or not header_token:
        return False

    if not hmac.compare_digest(cookie_token, header_token):
        return False

    return validate_csrf_token(cookie_token)


def is_origin_allowed(
    origin: str | None,
    allowed_origins: Iterable[str],
) -> bool:
    """
    Validate a request Origin against explicitly configured origins.

    Origins are compared by scheme, hostname and effective port.
    """
    if not origin:
        return False

    try:
        parsed_origin = urlparse(origin)

        if (
            parsed_origin.scheme not in {"http", "https"}
            or not parsed_origin.hostname
            or parsed_origin.username
            or parsed_origin.password
            or parsed_origin.path not in {"", "/"}
            or parsed_origin.params
            or parsed_origin.query
            or parsed_origin.fragment
        ):
            return False

        origin_port = parsed_origin.port or (
            443 if parsed_origin.scheme == "https" else 80
        )

        normalized_origin = (
            parsed_origin.scheme.lower(),
            parsed_origin.hostname.lower(),
            origin_port,
        )

        for configured_origin in allowed_origins:
            parsed_allowed = urlparse(configured_origin)

            if (
                parsed_allowed.scheme not in {"http", "https"}
                or not parsed_allowed.hostname
                or parsed_allowed.username
                or parsed_allowed.password
                or parsed_allowed.path not in {"", "/"}
                or parsed_allowed.params
                or parsed_allowed.query
                or parsed_allowed.fragment
            ):
                continue

            allowed_port = parsed_allowed.port or (
                443 if parsed_allowed.scheme == "https" else 80
            )

            normalized_allowed = (
                parsed_allowed.scheme.lower(),
                parsed_allowed.hostname.lower(),
                allowed_port,
            )

            if normalized_origin == normalized_allowed:
                return True

        return False

    except ValueError:
        return False


def enforce_csrf_protection(request: Request) -> bool:
    """
    Validate CSRF protection for a Starlette request.

    This helper is available for dependencies and endpoint-level
    checks. The middleware performs the actual request enforcement.
    """
    settings = get_settings()

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)

    if not validate_csrf_pair(cookie_token, header_token):
        return False

    origin = request.headers.get("Origin")

    if origin:
        return is_origin_allowed(
            origin,
            settings.cors_origins,
        )

    return True


class CSRFMiddleware:
    """
    ASGI middleware implementing CSRF validation.

    Safe methods are allowed without a token. Unsafe methods
    require a valid signed double-submit cookie and matching
    X-CSRF-Token header.

    Requests with an Origin header must also originate from
    a configured allowed origin.
    """

    def __init__(
        self,
        app: ASGIApp,
        exempt_paths: Iterable[str] | None = None,
    ) -> None:
        self.app = app

        self.exempt_paths = set(DEFAULT_EXEMPT_PATHS)

        if exempt_paths:
            self.exempt_paths.update(exempt_paths)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_method = scope.get("method", "GET").upper()
        request_path = scope.get("path", "/")

        if (
            request_method in SAFE_METHODS
            or request_path in self.exempt_paths
        ):
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        headers = Headers(scope=scope)

        origin = headers.get("Origin")

        if origin and not is_origin_allowed(
            origin,
            settings.cors_origins,
        ):
            response = JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "error": {
                        "code": "CSRF_ORIGIN_REJECTED",
                        "message": "Request origin is not permitted.",
                    },
                },
            )

            await response(scope, receive, send)
            return

        cookies = self._parse_cookies(headers.get("Cookie", ""))

        cookie_token = cookies.get(CSRF_COOKIE_NAME)
        header_token = headers.get(CSRF_HEADER_NAME)

        if not validate_csrf_pair(
            cookie_token,
            header_token,
        ):
            response = JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "error": {
                        "code": "CSRF_VALIDATION_FAILED",
                        "message": "CSRF token validation failed.",
                    },
                },
            )

            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _parse_cookies(cookie_header: str) -> dict[str, str]:
        """Parse cookie header values without relying on request state."""
        from http.cookies import SimpleCookie

        cookie = SimpleCookie()

        try:
            cookie.load(cookie_header)
        except Exception:
            return {}

        return {
            name: morsel.value
            for name, morsel in cookie.items()
        }


def set_csrf_cookie(
    response: Response,
    token: str | None = None,
    secure: bool = True,
) -> str:
    """
    Set a signed CSRF cookie and return its token.

    Call this from a browser-facing endpoint, such as a CSRF
    bootstrap endpoint, before making state-changing requests.
    """
    csrf_token = token or create_signed_csrf_token()

    if not validate_csrf_token(csrf_token):
        raise ValueError("Invalid CSRF token")

    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )

    return csrf_token
