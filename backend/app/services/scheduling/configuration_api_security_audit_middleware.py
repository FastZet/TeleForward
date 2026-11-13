
"""ASGI middleware for configuration API security auditing."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services.scheduling.configuration_api_security_audit_integration import (
    SecurityAuditIntegrationError,
    record_rate_limit_rejection,
    record_request_rejection,
)


logger = logging.getLogger(__name__)

IdentityResolver = Callable[[Scope], str | None | Awaitable[str | None]]
RateLimitCheck = Callable[[Scope, str | None], bool | Awaitable[bool]]


class SecurityAuditMiddleware:
    """Audit rejected HTTP requests while preserving normal ASGI behavior.

    The middleware does not authenticate users itself. An optional identity
    resolver can supply a principal identifier for audit attribution.

    A rate-limit callback returns True when the request is allowed and
    False when it must be rejected.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        audit_app: Any,
        identity_resolver: IdentityResolver | None = None,
        rate_limit_check: RateLimitCheck | None = None,
        max_request_body_bytes: int | None = None,
        audit_unhandled_exceptions: bool = True,
    ) -> None:
        if not callable(app):
            raise TypeError("app must be an ASGI application")

        if audit_app is None:
            raise ValueError("audit_app is required")

        if (
            max_request_body_bytes is not None
            and (
                isinstance(max_request_body_bytes, bool)
                or not isinstance(max_request_body_bytes, int)
                or max_request_body_bytes < 1
            )
        ):
            raise ValueError(
                "max_request_body_bytes must be a positive integer"
            )

        self.app = app
        self.audit_app = audit_app
        self.identity_resolver = identity_resolver
        self.rate_limit_check = rate_limit_check
        self.max_request_body_bytes = max_request_body_bytes
        self.audit_unhandled_exceptions = audit_unhandled_exceptions

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        principal_id: str | None = None

        try:
            principal_id = await self._resolve_identity(scope)

            if not self._is_preflight_request(scope):
                allowed = await self._check_rate_limit(
                    scope,
                    principal_id,
                )

                if not allowed:
                    await self._reject(
                        scope,
                        receive,
                        send,
                        status_code=429,
                        reason="rate_limit_exceeded",
                        principal_id=principal_id,
                        rate_limited=True,
                    )
                    return

            if self.max_request_body_bytes is not None:
                content_length = self._get_content_length(scope)

                if (
                    content_length is not None
                    and content_length > self.max_request_body_bytes
                ):
                    await self._reject(
                        scope,
                        receive,
                        send,
                        status_code=413,
                        reason="payload_too_large",
                        principal_id=principal_id,
                    )
                    return

                replay_receive = await self._buffer_request_body(
                    receive,
                    self.max_request_body_bytes,
                )

                if replay_receive is None:
                    await self._reject(
                        scope,
                        receive,
                        send,
                        status_code=413,
                        reason="payload_too_large",
                        principal_id=principal_id,
                    )
                    return

                receive = replay_receive

            await self.app(scope, receive, send)

        except Exception as exc:
            if self.audit_unhandled_exceptions:
                self._audit_safely(
                    reason="unhandled_application_exception",
                    principal_id=principal_id,
                    scope=scope,
                    metadata={
                        "exception_type": type(exc).__name__,
                    },
                )
            raise

    async def _resolve_identity(self, scope: Scope) -> str | None:
        if self.identity_resolver is None:
            return None

        result = self.identity_resolver(scope)

        if hasattr(result, "__await__"):
            result = await result

        if result is None:
            return None

        if not isinstance(result, str) or not result.strip():
            raise ValueError(
                "identity_resolver must return a non-empty string or None"
            )

        return result

    async def _check_rate_limit(
        self,
        scope: Scope,
        principal_id: str | None,
    ) -> bool:
        if self.rate_limit_check is None:
            return True

        result = self.rate_limit_check(scope, principal_id)

        if hasattr(result, "__await__"):
            result = await result

        if not isinstance(result, bool):
            raise TypeError("rate_limit_check must return bool")

        return result

    @staticmethod
    def _is_preflight_request(scope: Scope) -> bool:
        method = scope.get("method", "").upper()
        headers = {
            key.lower(): value
            for key, value in scope.get("headers", [])
        }

        return (
            method == "OPTIONS"
            and "origin" in headers
            and "access-control-request-method" in headers
        )

    @staticmethod
    def _get_content_length(scope: Scope) -> int | None:
        headers = [
            value
            for key, value in scope.get("headers", [])
            if key.lower() == b"content-length"
        ]

        if not headers:
            return None

        if len(headers) != 1:
            raise ValueError("Multiple Content-Length headers are not allowed")

        try:
            length = int(headers[0].decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("Invalid Content-Length header") from exc

        if length < 0:
            raise ValueError("Content-Length cannot be negative")

        return length

    @staticmethod
    async def _buffer_request_body(
        receive: Receive,
        maximum_bytes: int,
    ) -> Receive | None:
        """Buffer a bounded HTTP request body for replay downstream."""
        messages: list[dict[str, Any]] = []
        total_bytes = 0

        while True:
            message = await receive()

            if message["type"] == "http.disconnect":
                messages.append(message)
                break

            if message["type"] != "http.request":
                messages.append(message)
                continue

            body = message.get("body", b"")
            total_bytes += len(body)

            if total_bytes > maximum_bytes:
                return None

            messages.append(message)

            if not message.get("more_body", False):
                break

        position = 0

        async def replay_receive() -> dict[str, Any]:
            nonlocal position

            if position < len(messages):
                message = messages[position]
                position += 1
                return message

            # The original request body has already been consumed.
            # Subsequent receives should not block waiting for new data.
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        return replay_receive

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        reason: str,
        principal_id: str | None,
        rate_limited: bool = False,
    ) -> None:
        self._audit_safely(
            reason=reason,
            principal_id=principal_id,
            scope=scope,
            rate_limited=rate_limited,
        )

        response = JSONResponse(
            status_code=status_code,
            content={
                "detail": reason,
            },
        )

        await response(scope, receive, send)

    def _audit_safely(
        self,
        *,
        reason: str,
        principal_id: str | None,
        scope: Scope,
        rate_limited: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Audit without allowing logging failures to break the request."""
        try:
            method = scope.get("method")
            path = scope.get("path")

            client = scope.get("client")
            source_ip = (
                client[0]
                if isinstance(client, (tuple, list)) and client
                else None
            )

            if rate_limited:
                record_rate_limit_rejection(
                    self.audit_app,
                    principal_id=principal_id,
                    path=path,
                    method=method,
                    source_ip=source_ip,
                    metadata=metadata,
                )
            else:
                record_request_rejection(
                    self.audit_app,
                    reason=reason,
                    principal_id=principal_id,
                    path=path,
                    method=method,
                    source_ip=source_ip,
                    metadata=metadata,
                )

        except SecurityAuditIntegrationError:
            logger.error(
                "Security audit logger is unavailable; rejection was not recorded"
            )
        except Exception:
            logger.exception("Failed to record security audit event")


__all__ = [
    "IdentityResolver",
    "RateLimitCheck",
    "SecurityAuditMiddleware",
]
