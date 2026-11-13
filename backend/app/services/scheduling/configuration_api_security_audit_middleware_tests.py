
"""Tests for configuration API security audit middleware."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditEventType,
    SecurityAuditLogger,
)
from app.services.scheduling.configuration_api_security_audit_integration import (
    install_configuration_api_security_audit,
)
from app.services.scheduling.configuration_api_security_audit_middleware import (
    SecurityAuditMiddleware,
)


class ASGIHarness:
    """Minimal ASGI test harness."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        method: str = "POST",
        path: str = "/api/v1/configuration",
        headers: list[tuple[bytes, bytes]] | None = None,
        body: bytes = b"",
        client: tuple[str, int] = ("192.0.2.10", 50000),
    ) -> None:
        self.app = app
        self.method = method
        self.path = path
        self.headers = headers or []
        self.body = body
        self.client = client
        self.sent: list[Message] = []

    async def run(self) -> list[Message]:
        delivered = False

        async def receive() -> Message:
            nonlocal delivered

            if delivered:
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }

            delivered = True
            return {
                "type": "http.request",
                "body": self.body,
                "more_body": False,
            }

        async def send(message: Message) -> None:
            self.sent.append(message)

        scope: Scope = {
            "type": "http",
            "asgi": {
                "version": "3.0",
                "spec_version": "2.3",
            },
            "http_version": "1.1",
            "method": self.method,
            "scheme": "http",
            "path": self.path,
            "raw_path": self.path.encode("ascii"),
            "query_string": b"",
            "headers": self.headers,
            "client": self.client,
            "server": ("testserver", 80),
        }

        await self.app(scope, receive, send)
        return self.sent

    @property
    def status_code(self) -> int | None:
        for message in self.sent:
            if message["type"] == "http.response.start":
                return message["status"]
        return None

    @property
    def response_body(self) -> bytes:
        return b"".join(
            message.get("body", b"")
            for message in self.sent
            if message["type"] == "http.response.body"
        )


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "security.jsonl"


@pytest.fixture
def audit_logger(audit_path: Path):
    logger = SecurityAuditLogger(audit_path, fsync=False)
    try:
        yield logger
    finally:
        logger.close()


def make_app(
    audit_logger: SecurityAuditLogger,
    downstream: ASGIApp | None = None,
    **middleware_options: Any,
) -> SecurityAuditMiddleware:
    if downstream is None:

        async def downstream(
            scope: Scope,
            receive: Receive,
            send: Send,
        ) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"status":"ok"}',
                    "more_body": False,
                }
            )

    from fastapi import FastAPI

    audit_app = FastAPI()
    install_configuration_api_security_audit(
        audit_app,
        audit_logger,
    )

    return SecurityAuditMiddleware(
        downstream,
        audit_app=audit_app,
        **middleware_options,
    )


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_constructor_rejects_non_callable_app(
    audit_logger: SecurityAuditLogger,
) -> None:
    from fastapi import FastAPI

    audit_app = FastAPI()

    with pytest.raises(TypeError):
        SecurityAuditMiddleware(
            object(),  # type: ignore[arg-type]
            audit_app=audit_app,
        )


def test_constructor_requires_audit_app(
    audit_logger: SecurityAuditLogger,
) -> None:
    async def downstream(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        return None

    with pytest.raises(ValueError):
        SecurityAuditMiddleware(
            downstream,
            audit_app=None,
        )


@pytest.mark.parametrize("maximum", [0, -1, True, 1.5, "100"])
def test_constructor_rejects_invalid_body_limit(
    audit_logger: SecurityAuditLogger,
    maximum: Any,
) -> None:
    from fastapi import FastAPI

    with pytest.raises(ValueError):
        SecurityAuditMiddleware(
            lambda scope, receive, send: None,  # type: ignore[arg-type]
            audit_app=FastAPI(),
            max_request_body_bytes=maximum,
        )


# ---------------------------------------------------------------------------
# Normal request handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_request_reaches_downstream(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(audit_logger)
    harness = ASGIHarness(middleware)

    await harness.run()

    assert harness.status_code == 200
    assert json.loads(harness.response_body) == {"status": "ok"}
    assert audit_logger.read_events() == []


@pytest.mark.asyncio
async def test_non_http_scope_bypasses_http_security_checks(
    audit_logger: SecurityAuditLogger,
) -> None:
    received: list[Scope] = []

    async def downstream(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        received.append(scope)

    middleware = make_app(
        audit_logger,
        downstream,
        rate_limit_check=lambda scope, principal: False,
        max_request_body_bytes=1,
    )

    scope: Scope = {
        "type": "lifespan",
        "asgi": {"version": "3.0"},
    }

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        return None

    await middleware(scope, receive, send)

    assert received == [scope]
    assert audit_logger.read_events() == []


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_identity_resolver_is_supported(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        identity_resolver=lambda scope: "admin-1",
        rate_limit_check=lambda scope, principal: False,
    )

    harness = ASGIHarness(middleware)
    await harness.run()

    record = audit_logger.read_events()[0]
    assert record["principal_id"] == "admin-1"


@pytest.mark.asyncio
async def test_async_identity_resolver_is_supported(
    audit_logger: SecurityAuditLogger,
) -> None:
    async def resolve(scope: Scope) -> str:
        return "operator-1"

    middleware = make_app(
        audit_logger,
        identity_resolver=resolve,
        rate_limit_check=lambda scope, principal: False,
    )

    harness = ASGIHarness(middleware)
    await harness.run()

    record = audit_logger.read_events()[0]
    assert record["principal_id"] == "operator-1"


@pytest.mark.asyncio
async def test_identity_resolver_can_return_none(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        identity_resolver=lambda scope: None,
        rate_limit_check=lambda scope, principal: False,
    )

    harness = ASGIHarness(middleware)
    await harness.run()

    assert audit_logger.read_events()[0]["principal_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["", " ", 123, object()])
async def test_invalid_identity_result_is_rejected(
    audit_logger: SecurityAuditLogger,
    invalid: Any,
) -> None:
    middleware = make_app(
        audit_logger,
        identity_resolver=lambda scope: invalid,
    )

    harness = ASGIHarness(middleware)

    with pytest.raises(ValueError):
        await harness.run()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_allows_request(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        rate_limit_check=lambda scope, principal: True,
    )

    harness = ASGIHarness(middleware)
    await harness.run()

    assert harness.status_code == 200
    assert audit_logger.read_events() == []


@pytest.mark.asyncio
async def test_rate_limit_rejects_request(
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    middleware = make_app(
        audit_logger,
        rate_limit_check=lambda scope, principal: False,
    )

    harness = ASGIHarness(middleware)
    await harness.run()

    assert harness.status_code == 429
    assert json.loads(harness.response_body) == {
        "detail": "rate_limit_exceeded"
    }

    records = read_records(audit_path)
    assert len(records) == 1
    assert records[0]["event_type"] == "rate_limit_rejected"
    assert records[0]["success"] is False
    assert records[0]["metadata"]["reason"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_async_rate_limit_callback_is_supported(
    audit_logger: SecurityAuditLogger,
) -> None:
    async def check(
        scope: Scope,
        principal_id: str | None,
    ) -> bool:
        return False

    middleware = make_app(
        audit_logger,
        rate_limit_check=check,
    )

    harness = ASGIHarness(middleware)
    await harness.run()

    assert harness.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_callback_receives_resolved_identity(
    audit_logger: SecurityAuditLogger,
) -> None:
    observed: list[str | None] = []

    def check(
        scope: Scope,
        principal_id: str | None,
    ) -> bool:
        observed.append(principal_id)
        return True

    middleware = make_app(
        audit_logger,
        identity_resolver=lambda scope: "admin-1",
        rate_limit_check=check,
    )

    harness = ASGIHarness(middleware)
    await harness.run()

    assert observed == ["admin-1"]


@pytest.mark.asyncio
async def test_rate_limit_callback_must_return_boolean(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        rate_limit_check=lambda scope, principal: "allowed",  # type: ignore[arg-type]
    )

    harness = ASGIHarness(middleware)

    with pytest.raises(TypeError):
        await harness.run()


@pytest.mark.asyncio
async def test_preflight_options_request_bypasses_rate_limit(
    audit_logger: SecurityAuditLogger,
) -> None:
    called = False

    def reject(
        scope: Scope,
        principal_id: str | None,
    ) -> bool:
        nonlocal called
        called = True
        return False

    middleware = make_app(
        audit_logger,
        rate_limit_check=reject,
    )

    harness = ASGIHarness(
        middleware,
        method="OPTIONS",
        headers=[
            (b"origin", b"https://example.test"),
            (b"access-control-request-method", b"POST"),
        ],
    )

    await harness.run()

    assert harness.status_code == 200
    assert called is False
    assert audit_logger.read_events() == []


@pytest.mark.asyncio
async def test_plain_options_request_does_not_bypass_rate_limit(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        rate_limit_check=lambda scope, principal: False,
    )

    harness = ASGIHarness(
        middleware,
        method="OPTIONS",
        headers=[(b"origin", b"https://example.test")],
    )

    await harness.run()

    assert harness.status_code == 429


# ---------------------------------------------------------------------------
# Request body size enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_small_request_body_is_allowed(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        max_request_body_bytes=10,
    )

    harness = ASGIHarness(
        middleware,
        body=b"12345",
        headers=[(b"content-length", b"5")],
    )

    await harness.run()

    assert harness.status_code == 200


@pytest.mark.asyncio
async def test_content_length_over_limit_is_rejected(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        max_request_body_bytes=5,
    )

    harness = ASGIHarness(
        middleware,
        body=b"123456",
        headers=[(b"content-length", b"6")],
    )

    await harness.run()

    assert harness.status_code == 413
    assert json.loads(harness.response_body)["detail"] == "payload_too_large"

    record = audit_logger.read_events()[0]
    assert record["event_type"] == "request_rejected"
    assert record["metadata"]["reason"] == "payload_too_large"


@pytest.mark.asyncio
async def test_streamed_body_over_limit_is_rejected(
    audit_logger: SecurityAuditLogger,
) -> None:
    downstream_called = False

    async def downstream(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        nonlocal downstream_called
        downstream_called = True

    middleware = make_app(
        audit_logger,
        downstream,
        max_request_body_bytes=5,
    )

    messages = [
        {
            "type": "http.request",
            "body": b"123",
            "more_body": True,
        },
        {
            "type": "http.request",
            "body": b"456",
            "more_body": False,
        },
    ]
    position = 0

    async def receive() -> Message:
        nonlocal position
        message = messages[position]
        position += 1
        return message

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/upload",
        "raw_path": b"/upload",
        "query_string": b"",
        "headers": [],
        "client": ("192.0.2.10", 50000),
        "server": ("testserver", 80),
    }

    await middleware(scope, receive, send)

    assert downstream_called is False
    assert next(
        message["status"]
        for message in sent
        if message["type"] == "http.response.start"
    ) == 413


@pytest.mark.asyncio
async def test_body_is_replayed_to_downstream(
    audit_logger: SecurityAuditLogger,
) -> None:
    observed_body = bytearray()

    async def downstream(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        while True:
            message = await receive()

            if message["type"] == "http.disconnect":
                break

            observed_body.extend(message.get("body", b""))

            if not message.get("more_body", False):
                break

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"",
                "more_body": False,
            }
        )

    middleware = make_app(
        audit_logger,
        downstream,
        max_request_body_bytes=10,
    )

    harness = ASGIHarness(
        middleware,
        body=b"hello",
        headers=[(b"content-length", b"5")],
    )

    await harness.run()

    assert harness.status_code == 200
    assert observed_body == b"hello"


@pytest.mark.asyncio
async def test_invalid_content_length_is_rejected(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        max_request_body_bytes=10,
    )

    harness = ASGIHarness(
        middleware,
        headers=[(b"content-length", b"not-a-number")],
    )

    with pytest.raises(ValueError):
        await harness.run()


@pytest.mark.asyncio
async def test_duplicate_content_length_is_rejected(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        max_request_body_bytes=10,
    )

    harness = ASGIHarness(
        middleware,
        headers=[
            (b"content-length", b"5"),
            (b"content-length", b"5"),
        ],
    )

    with pytest.raises(ValueError):
        await harness.run()


# ---------------------------------------------------------------------------
# Audit failure handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_audit_logger_does_not_break_rate_limit_rejection(
    audit_logger: SecurityAuditLogger,
) -> None:
    from fastapi import FastAPI

    async def downstream(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        return None

    middleware = SecurityAuditMiddleware(
        downstream,
        audit_app=FastAPI(),
        rate_limit_check=lambda scope, principal: False,
    )

    harness = ASGIHarness(middleware)
    await harness.run()

    assert harness.status_code == 429


@pytest.mark.asyncio
async def test_downstream_exception_is_propagated(
    audit_logger: SecurityAuditLogger,
) -> None:
    async def downstream(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        raise RuntimeError("downstream failure")

    middleware = make_app(
        audit_logger,
        downstream,
    )

    harness = ASGIHarness(middleware)

    with pytest.raises(RuntimeError, match="downstream failure"):
        await harness.run()


@pytest.mark.asyncio
async def test_downstream_exception_is_audited(
    audit_logger: SecurityAuditLogger,
) -> None:
    async def downstream(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        raise RuntimeError("internal failure")

    middleware = make_app(
        audit_logger,
        downstream,
        identity_resolver=lambda scope: "admin-1",
    )

    harness = ASGIHarness(middleware)

    with pytest.raises(RuntimeError):
        await harness.run()

    record = audit_logger.read_events()[0]

    assert record["event_type"] == "request_rejected"
    assert record["principal_id"] == "admin-1"
    assert (
        record["metadata"]["exception_type"]
        == "RuntimeError"
    )


@pytest.mark.asyncio
async def test_unhandled_exception_auditing_can_be_disabled(
    audit_logger: SecurityAuditLogger,
) -> None:
    async def downstream(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        raise RuntimeError("internal failure")

    middleware = make_app(
        audit_logger,
        downstream,
        audit_unhandled_exceptions=False,
    )

    harness = ASGIHarness(middleware)

    with pytest.raises(RuntimeError):
        await harness.run()

    assert audit_logger.read_events() == []


# ---------------------------------------------------------------------------
# Client attribution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejection_records_client_address(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        rate_limit_check=lambda scope, principal: False,
    )

    harness = ASGIHarness(
        middleware,
        client=("198.51.100.20", 45000),
    )

    await harness.run()

    record = audit_logger.read_events()[0]
    assert record["metadata"]["source_ip"] == "198.51.100.20"


@pytest.mark.asyncio
async def test_rejection_without_client_address_is_supported(
    audit_logger: SecurityAuditLogger,
) -> None:
    middleware = make_app(
        audit_logger,
        rate_limit_check=lambda scope, principal: False,
    )

    harness = ASGIHarness(
        middleware,
        client=None,  # type: ignore[arg-type]
    )

    await harness.run()

    record = audit_logger.read_events()[0]
    assert record["metadata"].get("source_ip") is None
