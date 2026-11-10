"""ASGI middleware for scheduling configuration API security."""

from __future__ import annotations

import logging
from typing import Any, Callable

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services.scheduling.configuration_api_security import (
    ConfigurationApiRateLimiter,
    RateLimitPolicy,
)


logger = logging.getLogger(__name__)


class ConfigurationApiMiddleware:
    """Apply request-level protections to configuration API routes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_prefix: str = "/api/v1/scheduling/configuration",
        max_request_body_bytes: int = 1_048_576,
        rate_limiter: ConfigurationApiRateLimiter | None = None,
        identity_resolver: Callable[[Scope], str | None] | None = None,
        enabled: bool = True,
    ) -> None:
        if not callable(app):
            raise TypeError("app must be an ASGI application")

        if (
            not isinstance(api_prefix, str)
            or not api_prefix.startswith("/")
        ):
            raise ValueError("api_prefix must start with '/'")

        if (
            isinstance(max_request_body_bytes, bool)
            or not isinstance(max_request_body_bytes, int)
            or max_request_body_bytes < 1
        ):
            raise ValueError(
                "max_request_body_bytes must be a positive integer"
            )

        if identity_resolver is not None and not callable(identity_resolver):
            raise TypeError("identity_resolver must be callable")

        self.app = app
        self.api_prefix = api_prefix.rstrip("/")
        self.max_request_body_bytes = max_request_body_bytes
        self.rate_limiter = rate_limiter or ConfigurationApiRateLimiter(
            RateLimitPolicy()
        )
        self.identity_resolver = identity_resolver
        self.enabled = enabled

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        if not self.enabled or not self._is_configuration_path(path):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)

        content_length = headers.get("content-length")

        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                await self._reject(
                    send,
                    status_code=400,
                    code="INVALID_CONTENT_LENGTH",
                    message="Invalid Content-Length header",
                )
                return

            if declared_length < 0:
                await self._reject(
                    send,
                    status_code=400,
                    code="INVALID_CONTENT_LENGTH",
                    message="Invalid Content-Length header",
                )
                return

            if declared_length > self.max_request_body_bytes:
                await self._reject(
                    send,
                    status_code=413,
                    code="REQUEST_BODY_TOO_LARGE",
                    message="Request body exceeds the permitted size",
                )
                return

        identity = self._resolve_identity(scope)

        if identity is None:
            # Authentication remains the responsibility of the
            # application authentication dependency.
            identity = "anonymous"

        rate_result = await self.rate_limiter.check(identity)

        if not rate_result.allowed:
            await self._reject(
                send,
                status_code=429,
                code="RATE_LIMIT_EXCEEDED",
                message="Too many configuration API requests",
                headers={
                    "Retry-After": str(
                        max(1, int(rate_result.retry_after_seconds))
                    ),
                    "X-RateLimit-Limit": str(rate_result.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
            return

        async def send_with_security_headers(
            message: dict[str, Any],
        ) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(
                    message.get("headers", [])
                )

                response_headers.extend(
                    [
                        (
                            b"x-content-type-options",
                            b"nosniff",
                        ),
                        (
                            b"x-frame-options",
                            b"DENY",
                        ),
                        (
                            b"referrer-policy",
                            b"no-referrer",
                        ),
                        (
                            b"cache-control",
                            b"no-store",
                        ),
                        (
                            b"x-ratelimit-limit",
                            str(rate_result.limit).encode(),
                        ),
                        (
                            b"x-ratelimit-remaining",
                            str(rate_result.remaining).encode(),
                        ),
                    ]
                )

                message = {
                    **message,
                    "headers": response_headers,
                }

            await send(message)

        await self.app(
            scope,
            receive,
            send_with_security_headers,
        )

    def _is_configuration_path(self, path: str) -> bool:
        return (
            path == self.api_prefix
            or path.startswith(self.api_prefix + "/")
        )

    def _resolve_identity(self, scope: Scope) -> str | None:
        if self.identity_resolver is None:
            return None

        try:
            identity = self.identity_resolver(scope)

        except Exception:
            logger.exception(
                "Configuration API identity resolution failed"
            )
            return None

        if not isinstance(identity, str) or not identity.strip():
            return None

        return identity.strip()

    @staticmethod
    async def _reject(
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        response_headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        }

        if headers:
            response_headers.update(headers)

        response = JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "error": {
                    "code": code,
                    "message": message,
                },
            },
            headers=response_headers,
        )

        await response(scope=None, receive=None, send=send)
