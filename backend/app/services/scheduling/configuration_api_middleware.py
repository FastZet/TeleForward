
"""ASGI middleware for scheduling configuration API security."""

from __future__ import annotations

import inspect
import logging
from collections import deque
from typing import Any, Awaitable, Callable

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.scheduling.configuration_api_security import (
    ConfigurationApiRateLimiter,
    RateLimitPolicy,
)


logger = logging.getLogger(__name__)

IdentityResolver = Callable[
    [Scope],
    str | None | Awaitable[str | None],
]


class ConfigurationApiMiddleware:
    """Apply request-level protections to configuration API routes.

    Protections:
        - API path scoping
        - Request-body size enforcement
        - Identity-aware rate limiting
        - Security response headers
        - CORS preflight bypass

    Authentication and authorization remain the responsibility of
    the application's authentication and API dependency layers.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_prefix: str = "/api/v1/scheduling/configuration",
        max_request_body_bytes: int = 1_048_576,
        rate_limiter: ConfigurationApiRateLimiter | None = None,
        identity_resolver: IdentityResolver | None = None,
        enabled: bool = True,
    ) -> None:
        if not callable(app):
            raise TypeError("app must be an ASGI application")

        if (
            not isinstance(api_prefix, str)
            or not api_prefix.startswith("/")
            or not api_prefix.strip("/")
        ):
            raise ValueError(
                "api_prefix must be a non-empty absolute path"
            )

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

        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")

        self.app = app
        self.api_prefix = api_prefix.rstrip("/")
        self.max_request_body_bytes = max_request_body_bytes

        self.rate_limiter = (
            rate_limiter
            if rate_limiter is not None
            else ConfigurationApiRateLimiter(RateLimitPolicy())
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

        # Read and buffer the body before passing the request downstream.
        # This enforces the size limit even when Content-Length is absent.
        buffered_messages, body_too_large = await self._buffer_request_body(
            receive
        )

        if body_too_large:
            await self._reject(
                scope,
                self._replay_receive(buffered_messages, receive),
                send,
                status_code=413,
                code="REQUEST_BODY_TOO_LARGE",
                message="Request body exceeds the permitted size",
            )
            return

        request_receive = self._replay_receive(
            buffered_messages,
            receive,
        )

        headers = Headers(scope=scope)

        content_length = headers.get("content-length")

        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                await self._reject(
                    scope,
                    request_receive,
                    send,
                    status_code=400,
                    code="INVALID_CONTENT_LENGTH",
                    message="Invalid Content-Length header",
                )
                return

            if declared_length < 0:
                await self._reject(
                    scope,
                    request_receive,
                    send,
                    status_code=400,
                    code="INVALID_CONTENT_LENGTH",
                    message="Invalid Content-Length header",
                )
                return

            if declared_length > self.max_request_body_bytes:
                await self._reject(
                    scope,
                    request_receive,
                    send,
                    status_code=413,
                    code="REQUEST_BODY_TOO_LARGE",
                    message="Request body exceeds the permitted size",
                )
                return

        # CORS preflight requests should not consume the normal API
        # rate-limit allowance.
        if scope.get("method", "").upper() == "OPTIONS":
            await self._call_with_security_headers(
                scope,
                request_receive,
                send,
                rate_limit=None,
            )
            return

        try:
            identity = await self._resolve_identity(scope)
        except Exception:
            logger.exception(
                "Configuration API identity resolution failed"
            )
            await self._reject(
                scope,
                request_receive,
                send,
                status_code=503,
                code="IDENTITY_RESOLUTION_FAILED",
                message="Request security could not be evaluated",
            )
            return

        # If no authenticated identity is available, use the ASGI
        # connection address as the rate-limit key. Do not trust
        # arbitrary client-supplied identity headers.
        if identity is None:
            identity = self._resolve_client_identity(scope)

        try:
            rate_result = await self.rate_limiter.check(identity)
        except Exception:
            logger.exception(
                "Configuration API rate-limit check failed"
            )
            await self._reject(
                scope,
                request_receive,
                send,
                status_code=503,
                code="RATE_LIMIT_UNAVAILABLE",
                message="Request security could not be evaluated",
            )
            return

        if not rate_result.allowed:
            retry_after = max(
                1,
                int(rate_result.retry_after_seconds),
            )

            await self._reject(
                scope,
                request_receive,
                send,
                status_code=429,
                code="RATE_LIMIT_EXCEEDED",
                message="Too many configuration API requests",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(rate_result.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
            return

        await self._call_with_security_headers(
            scope,
            request_receive,
            send,
            rate_limit=rate_result,
        )

    async def _buffer_request_body(
        self,
        receive: Receive,
    ) -> tuple[list[Message], bool]:
        """Buffer request messages while enforcing the configured limit.

        The buffer is bounded by the configured limit plus at most one
        ASGI message that causes the limit to be exceeded.
        """

        messages: list[Message] = []
        total_bytes = 0

        while True:
            message = await receive()

            messages.append(message)

            if message["type"] == "http.disconnect":
                return messages, False

            if message["type"] != "http.request":
                continue

            body = message.get("body", b"")
            total_bytes += len(body)

            if total_bytes > self.max_request_body_bytes:
                return messages, True

            if not message.get("more_body", False):
                return messages, False

    @staticmethod
    def _replay_receive(
        messages: list[Message],
        original_receive: Receive,
    ) -> Receive:
        """Replay buffered ASGI messages before reading from the server."""

        buffered = deque(messages)

        async def receive() -> Message:
            if buffered:
                return buffered.popleft()

            return await original_receive()

        return receive

    async def _resolve_identity(self, scope: Scope) -> str | None:
        """Resolve an identity using the configured trusted resolver."""

        if self.identity_resolver is None:
            return None

        identity = self.identity_resolver(scope)

        if inspect.isawaitable(identity):
            identity = await identity

        if identity is None:
            return None

        if not isinstance(identity, str) or not identity.strip():
            raise ValueError(
                "Identity resolver returned an invalid identity"
            )

        return identity.strip()

    @staticmethod
    def _resolve_client_identity(scope: Scope) -> str:
        """Use the ASGI client address as a fallback rate-limit key."""

        client = scope.get("client")

        if client and client[0]:
            return f"ip:{client[0]}"

        # Avoid trusting user-controlled headers when the ASGI server
        # does not expose a client address.
        return "unknown-client"

    def _is_configuration_path(self, path: str) -> bool:
        """Check the configured API prefix without partial matches."""

        return (
            path == self.api_prefix
            or path.startswith(self.api_prefix + "/")
        )

    async def _call_with_security_headers(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        rate_limit: Any | None,
    ) -> None:
        """Forward the request and add security headers to responses."""

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(
                    message.get("headers", [])
                )

                headers_to_set = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"no-referrer",
                    b"cache-control": b"no-store",
                }

                if rate_limit is not None:
                    headers_to_set.update(
                        {
                            b"x-ratelimit-limit": str(
                                rate_limit.limit
                            ).encode("ascii"),
                            b"x-ratelimit-remaining": str(
                                rate_limit.remaining
                            ).encode("ascii"),
                        }
                    )

                # Replace existing values instead of adding duplicates.
                replaced_names = set(headers_to_set)

                response_headers = [
                    (name, value)
                    for name, value in response_headers
                    if name.lower() not in replaced_names
                ]

                response_headers.extend(headers_to_set.items())

                message = {
                    **message,
                    "headers": response_headers,
                }

            await send(message)

        await self.app(scope, receive, secured_send)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Return a consistent JSON error response."""

        response_headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
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

        await response(scope, receive, send)
