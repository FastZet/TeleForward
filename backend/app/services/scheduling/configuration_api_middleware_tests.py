
"""Tests for scheduling configuration API ASGI middleware."""

from __future__ import annotations

import json
from typing import Any

import pytest

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.scheduling.configuration_api_middleware import (
    ConfigurationApiMiddleware,
)


class FakeRateLimitResult:
    """Test rate-limit result."""

    def __init__(
        self,
        *,
        allowed: bool = True,
        limit: int = 10,
        remaining: int = 9,
        retry_after_seconds: float = 0,
    ) -> None:
        self.allowed = allowed
        self.limit = limit
        self.remaining = remaining
        self.retry_after_seconds = retry_after_seconds


class FakeRateLimiter:
    """Test double for the configuration API rate limiter."""

    def __init__(
        self,
        result: FakeRateLimitResult | None = None,
    ) -> None:
        self.result = result or FakeRateLimitResult()
        self.identities: list[str] = []
        self.calls = 0
        self.raise_error = False

    async def check(self, identity: str) -> FakeRateLimitResult:
        self.calls += 1
        self.identities.append(identity)

        if self.raise_error:
            raise RuntimeError("Rate limiter unavailable")

        return self.result


class FakeASGIApplication:
    """Minimal ASGI application used by middleware tests."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        body: bytes = b'{"success":true}',
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.calls = 0
        self.last_scope: Scope | None = None
        self.last_body = b""

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        self.calls += 1
        self.last_scope = scope

        body_parts: list[bytes] = []

        while True:
            message = await receive()

            if message["type"] == "http.disconnect":
                break

            if message["type"] != "http.request":
                continue

            body_parts.append(message.get("body", b""))

            if not message.get("more_body", False):
                break

        self.last_body = b"".join(body_parts)

        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                ],
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": self.body,
                "more_body": False,
            }
        )


def make_scope(
    *,
    path: str = "/api/v1/scheduling/configuration",
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
    client: tuple[str, int] = ("127.0.0.1", 12345),
) -> Scope:
    """Create a minimal HTTP ASGI scope."""

    return {
        "type": "http",
        "asgi": {
            "version": "3.0",
            "spec_version": "2.3",
        },
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": client,
        "server": ("testserver", 80),
    }


def make_receive(
    messages: list[Message],
) -> Receive:
    """Create a receive callable that returns supplied ASGI messages."""

    pending = list(messages)

    async def receive() -> Message:
        if pending:
            return pending.pop(0)

        return {
            "type": "http.request",
            "body": b"",
            "more_body": False,
        }

    return receive


async def invoke_middleware(
    middleware: ConfigurationApiMiddleware,
    *,
    scope: Scope | None = None,
    messages: list[Message] | None = None,
) -> list[Message]:
    """Invoke middleware and collect its outgoing ASGI messages."""

    outgoing: list[Message] = []

    async def send(message: Message) -> None:
        outgoing.append(message)

    await middleware(
        scope or make_scope(),
        make_receive(
            messages
            or [
                {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }
            ]
        ),
        send,
    )

    return outgoing


def response_status(messages: list[Message]) -> int:
    """Return the HTTP response status from collected ASGI messages."""

    response = next(
        message
        for message in messages
        if message["type"] == "http.response.start"
    )

    return int(response["status"])


def response_headers(
    messages: list[Message],
) -> dict[bytes, bytes]:
    """Return response headers as a lowercase-key dictionary."""

    response = next(
        message
        for message in messages
        if message["type"] == "http.response.start"
    )

    return {
        name.lower(): value
        for name, value in response.get("headers", [])
    }


def response_json(messages: list[Message]) -> dict[str, Any]:
    """Decode the response JSON body."""

    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )

    return json.loads(body.decode("utf-8"))


@pytest.mark.asyncio
async def test_allows_valid_configuration_request() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
        identity_resolver=lambda scope: "user-123",
    )

    messages = await invoke_middleware(middleware)

    assert response_status(messages) == 200
    assert app.calls == 1
    assert limiter.identities == ["user-123"]


@pytest.mark.asyncio
async def test_adds_security_headers() -> None:
    app = FakeASGIApplication()

    middleware = ConfigurationApiMiddleware(
        app,
        identity_resolver=lambda scope: "user-123",
    )

    messages = await invoke_middleware(middleware)
    headers = response_headers(messages)

    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"referrer-policy"] == b"no-referrer"
    assert headers[b"cache-control"] == b"no-store"


@pytest.mark.asyncio
async def test_adds_rate_limit_headers() -> None:
    app = FakeASGIApplication()

    limiter = FakeRateLimiter(
        FakeRateLimitResult(
            allowed=True,
            limit=20,
            remaining=17,
        )
    )

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
        identity_resolver=lambda scope: "user-123",
    )

    messages = await invoke_middleware(middleware)
    headers = response_headers(messages)

    assert headers[b"x-ratelimit-limit"] == b"20"
    assert headers[b"x-ratelimit-remaining"] == b"17"


@pytest.mark.asyncio
async def test_rejects_request_exceeding_content_length_limit() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()

    middleware = ConfigurationApiMiddleware(
        app,
        max_request_body_bytes=10,
        rate_limiter=limiter,
    )

    messages = await invoke_middleware(
        middleware,
        scope=make_scope(
            method="POST",
            headers=[(b"content-length", b"20")],
        ),
        messages=[
            {
                "type": "http.request",
                "body": b"x" * 20,
                "more_body": False,
            }
        ],
    )

    assert response_status(messages) == 413
    assert app.calls == 0
    assert limiter.calls == 0

    body = response_json(messages)
    assert body["error"]["code"] == "REQUEST_BODY_TOO_LARGE"


@pytest.mark.asyncio
async def test_rejects_chunked_request_exceeding_body_limit() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()

    middleware = ConfigurationApiMiddleware(
        app,
        max_request_body_bytes=10,
        rate_limiter=limiter,
    )

    messages = await invoke_middleware(
        middleware,
        scope=make_scope(method="POST"),
        messages=[
            {
                "type": "http.request",
                "body": b"123456",
                "more_body": True,
            },
            {
                "type": "http.request",
                "body": b"789012",
                "more_body": False,
            },
        ],
    )

    assert response_status(messages) == 413
    assert app.calls == 0
    assert limiter.calls == 0


@pytest.mark.asyncio
async def test_accepts_request_at_exact_body_limit() -> None:
    app = FakeASGIApplication()

    middleware = ConfigurationApiMiddleware(
        app,
        max_request_body_bytes=10,
        identity_resolver=lambda scope: "user-123",
    )

    body = b"1234567890"

    messages = await invoke_middleware(
        middleware,
        scope=make_scope(method="POST"),
        messages=[
            {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }
        ],
    )

    assert response_status(messages) == 200
    assert app.last_body == body


@pytest.mark.asyncio
async def test_rejects_invalid_content_length() -> None:
    app = FakeASGIApplication()

    middleware = ConfigurationApiMiddleware(app)

    messages = await invoke_middleware(
        middleware,
        scope=make_scope(
            method="POST",
            headers=[(b"content-length", b"invalid")],
        ),
    )

    assert response_status(messages) == 400
    assert app.calls == 0

    body = response_json(messages)
    assert body["error"]["code"] == "INVALID_CONTENT_LENGTH"


@pytest.mark.asyncio
async def test_rejects_negative_content_length() -> None:
    app = FakeASGIApplication()

    middleware = ConfigurationApiMiddleware(app)

    messages = await invoke_middleware(
        middleware,
        scope=make_scope(
            method="POST",
            headers=[(b"content-length", b"-1")],
        ),
    )

    assert response_status(messages) == 400
    assert app.calls == 0


@pytest.mark.asyncio
async def test_rejects_rate_limited_request() -> None:
    app = FakeASGIApplication()

    limiter = FakeRateLimiter(
        FakeRateLimitResult(
            allowed=False,
            limit=10,
            remaining=0,
            retry_after_seconds=30,
        )
    )

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
        identity_resolver=lambda scope: "user-123",
    )

    messages = await invoke_middleware(middleware)

    assert response_status(messages) == 429
    assert app.calls == 0

    headers = response_headers(messages)

    assert headers[b"retry-after"] == b"30"
    assert headers[b"x-ratelimit-limit"] == b"10"
    assert headers[b"x-ratelimit-remaining"] == b"0"

    body = response_json(messages)
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_supports_async_identity_resolver() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()

    async def resolve_identity(scope: Scope) -> str:
        return "async-user-456"

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
        identity_resolver=resolve_identity,
    )

    messages = await invoke_middleware(middleware)

    assert response_status(messages) == 200
    assert limiter.identities == ["async-user-456"]


@pytest.mark.asyncio
async def test_uses_client_ip_when_identity_is_unavailable() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
    )

    messages = await invoke_middleware(
        middleware,
        scope=make_scope(
            client=("192.0.2.10", 54321),
        ),
    )

    assert response_status(messages) == 200
    assert limiter.identities == ["ip:192.0.2.10"]


@pytest.mark.asyncio
async def test_uses_unknown_client_when_address_is_unavailable() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
    )

    messages = await invoke_middleware(
        middleware,
        scope=make_scope(client=None),
    )

    assert response_status(messages) == 200
    assert limiter.identities == ["unknown-client"]


@pytest.mark.asyncio
async def test_identity_resolver_failure_returns_service_unavailable() -> None:
    app = FakeASGIApplication()

    def resolve_identity(scope: Scope) -> str:
        raise RuntimeError("Identity service unavailable")

    middleware = ConfigurationApiMiddleware(
        app,
        identity_resolver=resolve_identity,
    )

    messages = await invoke_middleware(middleware)

    assert response_status(messages) == 503
    assert app.calls == 0

    body = response_json(messages)
    assert body["error"]["code"] == "IDENTITY_RESOLUTION_FAILED"


@pytest.mark.asyncio
async def test_rate_limiter_failure_returns_service_unavailable() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()
    limiter.raise_error = True

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
        identity_resolver=lambda scope: "user-123",
    )

    messages = await invoke_middleware(middleware)

    assert response_status(messages) == 503
    assert app.calls == 0

    body = response_json(messages)
    assert body["error"]["code"] == "RATE_LIMIT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_ignores_requests_outside_configuration_prefix() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
    )

    messages = await invoke_middleware(
        middleware,
        scope=make_scope(
            path="/api/v1/accounts",
        ),
    )

    assert response_status(messages) == 200
    assert app.calls == 1
    assert limiter.calls == 0


@pytest.mark.asyncio
async def test_does_not_match_similar_but_unrelated_prefix() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
    )

    messages = await invoke_middleware(
        middleware,
        scope=make_scope(
            path="/api/v1/scheduling/configuration-extra",
        ),
    )

    assert response_status(messages) == 200
    assert limiter.calls == 0


@pytest.mark.asyncio
async def test_bypasses_rate_limiting_for_options_requests() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
    )

    messages = await invoke_middleware(
        middleware,
        scope=make_scope(method="OPTIONS"),
    )

    assert response_status(messages) == 200
    assert app.calls == 1
    assert limiter.calls == 0

    headers = response_headers(messages)

    assert headers[b"x-content-type-options"] == b"nosniff"


@pytest.mark.asyncio
async def test_disabled_middleware_does_not_apply_protections() -> None:
    app = FakeASGIApplication()
    limiter = FakeRateLimiter()

    middleware = ConfigurationApiMiddleware(
        app,
        rate_limiter=limiter,
        enabled=False,
    )

    messages = await invoke_middleware(middleware)

    assert response_status(messages) == 200
    assert app.calls == 1
    assert limiter.calls == 0


@pytest.mark.asyncio
async def test_replaces_existing_security_headers_without_duplicates() -> None:
    class ExistingHeaderApplication:
        async def __call__(
            self,
            scope: Scope,
            receive: Receive,
            send: Send,
        ) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"x-frame-options", b"SAMEORIGIN"),
                        (b"cache-control", b"public"),
                    ],
                }
            )

            await send(
                {
                    "type": "http.response.body",
                    "body": b"ok",
                    "more_body": False,
                }
            )

    middleware = ConfigurationApiMiddleware(
        ExistingHeaderApplication(),
        identity_resolver=lambda scope: "user-123",
    )

    messages = await invoke_middleware(middleware)
    headers = response_headers(messages)

    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"cache-control"] == b"no-store"

    response_start = next(
        message
        for message in messages
        if message["type"] == "http.response.start"
    )

    frame_headers = [
        value
        for name, value in response_start["headers"]
        if name.lower() == b"x-frame-options"
    ]

    assert len(frame_headers) == 1


def test_rejects_invalid_api_prefix() -> None:
    with pytest.raises(ValueError):
        ConfigurationApiMiddleware(
            FakeASGIApplication(),
            api_prefix="",
        )

    with pytest.raises(ValueError):
        ConfigurationApiMiddleware(
            FakeASGIApplication(),
            api_prefix="api/configuration",
        )


def test_rejects_invalid_body_size() -> None:
    for invalid_value in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            ConfigurationApiMiddleware(
                FakeASGIApplication(),
                max_request_body_bytes=invalid_value,
            )


def test_rejects_invalid_enabled_value() -> None:
    with pytest.raises(TypeError):
        ConfigurationApiMiddleware(
            FakeASGIApplication(),
            enabled=1,
        )


def test_rejects_non_callable_identity_resolver() -> None:
    with pytest.raises(TypeError):
        ConfigurationApiMiddleware(
            FakeASGIApplication(),
            identity_resolver="not-callable",  # type: ignore[arg-type]
        )
