
"""
TeleForward API rate limiting.

Provides a centralised SlowAPI limiter for protecting API
endpoints against excessive request rates.
"""

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import get_settings


def get_client_identifier(request) -> str:
    """
    Identify the client making a request.

    By default, the remote address is used. Forwarded headers
    are deliberately not trusted here because they can be
    spoofed unless a trusted reverse proxy is configured.
    """
    return get_remote_address(request)


settings = get_settings()

limiter = Limiter(
    key_func=get_client_identifier,
    default_limits=[],
    enabled=settings.environment != "testing",
    headers_enabled=True,
    storage_uri="memory://",
    strategy="fixed-window",
)


def get_rate_limit_error() -> type[RateLimitExceeded]:
    """
    Return the SlowAPI rate-limit exception class.

    Exposed centrally so the application can register a
    consistent exception handler.
    """
    return RateLimitExceeded
