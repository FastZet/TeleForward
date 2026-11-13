
"""Integration tests for security audit middleware installation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditEventType,
    SecurityAuditLogger,
)
from app.services.scheduling.configuration_api_security_audit_integration import (
    get_configuration_api_security_audit_logger,
)
from app.services.scheduling.configuration_api_security_audit_middleware import (
    SecurityAuditMiddleware,
)
from app.services.scheduling.configuration_api_security_audit_middleware_integration import (
    MIDDLEWARE_CONFIGURATION_STATE_KEY,
    MIDDLEWARE_INSTALLATION_STATE_KEY,
    MIDDLEWARE_STATE_KEY,
    SecurityAuditMiddlewareIntegrationError,
    get_configuration_api_security_audit_middleware,
    get_configuration_api_security_audit_middleware_configuration,
    install_configuration_api_security_audit_middleware,
    is_configuration_api_security_audit_middleware_installed,
)


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "security-audit.jsonl"


@pytest.fixture
def audit_logger(audit_path: Path):
    logger = SecurityAuditLogger(audit_path, fsync=False)
    try:
        yield logger
    finally:
        logger.close()


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/api/v1/configuration")
    async def update_configuration() -> dict[str, str]:
        return {"status": "updated"}

    return application


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def is_middleware_registered(app: FastAPI) -> bool:
    return any(
        middleware.cls is SecurityAuditMiddleware
        for middleware in app.user_middleware
    )


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def test_install_registers_middleware(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    result = install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
    )

    assert result is SecurityAuditMiddleware
    assert is_middleware_registered(app)
    assert is_configuration_api_security_audit_middleware_installed(app)


def test_install_registers_audit_logger(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
    )

    assert (
        get_configuration_api_security_audit_logger(app)
        is audit_logger
    )


def test_install_stores_middleware_class_in_app_state(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
    )

    assert (
        getattr(app.state, MIDDLEWARE_STATE_KEY)
        is SecurityAuditMiddleware
    )


def test_install_sets_installed_state(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
    )

    assert getattr(app.state, MIDDLEWARE_INSTALLATION_STATE_KEY) is True


def test_install_stores_default_configuration(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
    )

    configuration = getattr(
        app.state,
        MIDDLEWARE_CONFIGURATION_STATE_KEY,
    )

    assert configuration == {
        "identity_resolver_configured": False,
        "rate_limit_check_configured": False,
        "max_request_body_bytes": None,
        "audit_unhandled_exceptions": True,
    }


def test_install_accepts_custom_configuration(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    def identity_resolver(scope: dict[str, Any]) -> str:
        return "admin-1"

    def rate_limit_check(
        scope: dict[str, Any],
        principal_id: str | None,
    ) -> bool:
        return True

    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
        identity_resolver=identity_resolver,
        rate_limit_check=rate_limit_check,
        max_request_body_bytes=1024,
        audit_unhandled_exceptions=False,
    )

    configuration = (
        get_configuration_api_security_audit_middleware_configuration(
            app
        )
    )

    assert configuration == {
        "identity_resolver_configured": True,
        "rate_limit_check_configured": True,
        "max_request_body_bytes": 1024,
        "audit_unhandled_exceptions": False,
    }


def test_install_rejects_non_fastapi_application(
    audit_logger: SecurityAuditLogger,
) -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit_middleware(
            object(),  # type: ignore[arg-type]
            audit_logger,
        )


def test_install_rejects_invalid_logger(app: FastAPI) -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit_middleware(
            app,
            object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "maximum",
    [0, -1, True, 1.5, "1024"],
)
def test_install_rejects_invalid_body_limit(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    maximum: Any,
) -> None:
    with pytest.raises(ValueError):
        install_configuration_api_security_audit_middleware(
            app,
            audit_logger,
            max_request_body_bytes=maximum,
        )

    assert not is_middleware_registered(app)


# ---------------------------------------------------------------------------
# Duplicate protection
# ---------------------------------------------------------------------------


def test_duplicate_installation_is_rejected(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
    )

    with pytest.raises(SecurityAuditMiddlewareIntegrationError):
        install_configuration_api_security_audit_middleware(
            app,
            audit_logger,
        )

    assert sum(
        middleware.cls is SecurityAuditMiddleware
        for middleware in app.user_middleware
    ) == 1


def test_replacement_is_explicitly_rejected(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    tmp_path: Path,
) -> None:
    replacement_logger = SecurityAuditLogger(
        tmp_path / "replacement.jsonl",
        fsync=False,
    )

    try:
        install_configuration_api_security_audit_middleware(
            app,
            audit_logger,
        )

        with pytest.raises(SecurityAuditMiddlewareIntegrationError):
            install_configuration_api_security_audit_middleware(
                app,
                replacement_logger,
                replace_existing=True,
            )

        assert (
            get_configuration_api_security_audit_logger(app)
            is audit_logger
        )
    finally:
        replacement_logger.close()


# ---------------------------------------------------------------------------
# Installation timing and failure handling
# ---------------------------------------------------------------------------


def test_install_fails_after_middleware_stack_is_built(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    # Explicitly build the Starlette middleware stack.
    app.middleware_stack = app.build_middleware_stack()

    with pytest.raises(SecurityAuditMiddlewareIntegrationError):
        install_configuration_api_security_audit_middleware(
            app,
            audit_logger,
        )

    assert not is_middleware_registered(app)


def test_failed_registration_does_not_mark_middleware_installed(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    app.middleware_stack = app.build_middleware_stack()

    with pytest.raises(SecurityAuditMiddlewareIntegrationError):
        install_configuration_api_security_audit_middleware(
            app,
            audit_logger,
        )

    assert (
        getattr(app.state, MIDDLEWARE_INSTALLATION_STATE_KEY, False)
        is not True
    )


def test_failed_registration_can_leave_logger_registered(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    app.middleware_stack = app.build_middleware_stack()

    with pytest.raises(SecurityAuditMiddlewareIntegrationError):
        install_configuration_api_security_audit_middleware(
            app,
            audit_logger,
        )

    # Current installer behavior: logger registration precedes
    # middleware registration and is not rolled back on failure.
    assert (
        get_configuration_api_security_audit_logger(app)
        is audit_logger
    )


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def test_installed_status_is_false_before_installation(
    app: FastAPI,
) -> None:
    assert (
        is_configuration_api_security_audit_middleware_installed(app)
        is False
    )


def test_installed_status_is_true_after_installation(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
    )

    assert (
        is_configuration_api_security_audit_middleware_installed(app)
        is True
    )


def test_get_middleware_returns_registered_class(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
    )

    assert (
        get_configuration_api_security_audit_middleware(app)
        is SecurityAuditMiddleware
    )


def test_get_middleware_raises_before_installation(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditMiddlewareIntegrationError):
        get_configuration_api_security_audit_middleware(app)


def test_get_configuration_returns_defensive_copy(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
        max_request_body_bytes=2048,
    )

    configuration = (
        get_configuration_api_security_audit_middleware_configuration(
            app
        )
    )

    configuration["max_request_body_bytes"] = 1

    stored = (
        get_configuration_api_security_audit_middleware_configuration(
            app
        )
    )

    assert stored["max_request_body_bytes"] == 2048


def test_get_configuration_raises_before_installation(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditMiddlewareIntegrationError):
        get_configuration_api_security_audit_middleware_configuration(
            app
        )


def test_accessors_reject_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        is_configuration_api_security_audit_middleware_installed(
            object()  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError):
        get_configuration_api_security_audit_middleware(
            object()  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError):
        get_configuration_api_security_audit_middleware_configuration(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Actual HTTP requests
# ---------------------------------------------------------------------------


def test_normal_http_request_passes_through_middleware(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert audit_logger.read_events() == []


def test_rate_limited_http_request_is_audited(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
        identity_resolver=lambda scope: "admin-1",
        rate_limit_check=lambda scope, principal: False,
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/configuration")

    assert response.status_code == 429
    assert response.json()["detail"] == "rate_limit_exceeded"

    records = read_records(audit_path)

    assert len(records) == 1
    assert records[0]["event_type"] == "rate_limit_rejected"
    assert records[0]["principal_id"] == "admin-1"
    assert records[0]["success"] is False


def test_oversized_http_request_is_audited(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
        max_request_body_bytes=5,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/configuration",
            content=b"123456",
            headers={"content-type": "application/octet-stream"},
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "payload_too_large"

    records = read_records(audit_path)

    assert len(records) == 1
    assert records[0]["event_type"] == "request_rejected"
    assert records[0]["metadata"]["reason"] == "payload_too_large"


def test_allowed_http_request_does_not_create_audit_event(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
        rate_limit_check=lambda scope, principal: True,
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/configuration")

    assert response.status_code == 200
    assert audit_logger.read_events() == []


def test_preflight_request_is_not_rate_limited(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    called = False

    def reject(
        scope: dict[str, Any],
        principal_id: str | None,
    ) -> bool:
        nonlocal called
        called = True
        return False

    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
        rate_limit_check=reject,
    )

    with TestClient(app) as client:
        response = client.options(
            "/api/v1/configuration",
            headers={
                "Origin": "https://example.test",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 405
    assert called is False
    assert audit_logger.read_events() == []


def test_installed_middleware_uses_configured_body_limit(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
        max_request_body_bytes=4,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/configuration",
            content=b"12345",
        )

    assert response.status_code == 413


def test_installed_middleware_uses_configured_identity_resolver(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
        identity_resolver=lambda scope: "operator-7",
        rate_limit_check=lambda scope, principal: False,
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/configuration")

    assert response.status_code == 429

    record = audit_logger.read_events()[0]
    assert record["principal_id"] == "operator-7"


# ---------------------------------------------------------------------------
# Multiple application isolation
# ---------------------------------------------------------------------------


def test_separate_applications_have_separate_audit_loggers(
    tmp_path: Path,
) -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    first_logger = SecurityAuditLogger(
        tmp_path / "first.jsonl",
        fsync=False,
    )
    second_logger = SecurityAuditLogger(
        tmp_path / "second.jsonl",
        fsync=False,
    )

    try:
        install_configuration_api_security_audit_middleware(
            first_app,
            first_logger,
            rate_limit_check=lambda scope, principal: False,
        )
        install_configuration_api_security_audit_middleware(
            second_app,
            second_logger,
            rate_limit_check=lambda scope, principal: True,
        )

        with TestClient(first_app) as first_client:
            first_response = first_client.get("/")

        with TestClient(second_app) as second_client:
            second_response = second_client.get("/")

        assert first_response.status_code == 429
        assert second_response.status_code == 404

        assert len(first_logger.read_events()) == 1
        assert second_logger.read_events() == []
    finally:
        first_logger.close()
        second_logger.close()


# ---------------------------------------------------------------------------
# Middleware ordering
# ---------------------------------------------------------------------------


def test_middleware_is_registered_in_starlette_stack(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_middleware(
        app,
        audit_logger,
    )

    assert any(
        middleware.cls is SecurityAuditMiddleware
        for middleware in app.user_middleware
    )

    # Building the stack should instantiate the registered middleware.
    stack = app.build_middleware_stack()

    assert stack is not None
