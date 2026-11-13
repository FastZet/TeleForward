
"""Tests for configuration API security audit integration."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditEventType,
    SecurityAuditLogger,
)
from app.services.scheduling.configuration_api_security_audit_integration import (
    AUDIT_INSTALLATION_STATE_KEY,
    AUDIT_STATE_KEY,
    SecurityAuditIntegrationError,
    get_configuration_api_security_audit_logger,
    install_configuration_api_security_audit,
    is_configuration_api_security_audit_installed,
    record_authentication_result,
    record_authorization_result,
    record_rate_limit_rejection,
    record_request_rejection,
    record_security_audit_event,
    remove_configuration_api_security_audit,
)


UTC = timezone.utc


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def audit_log_path(tmp_path: Path) -> Path:
    return tmp_path / "security-audit.jsonl"


@pytest.fixture
def audit_logger(audit_log_path: Path):
    logger = SecurityAuditLogger(audit_log_path)
    try:
        yield logger
    finally:
        logger.close()


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


# ---------------------------------------------------------------------------
# Installation and retrieval
# ---------------------------------------------------------------------------


def test_install_registers_logger(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    installed = install_configuration_api_security_audit(
        app,
        audit_logger,
    )

    assert installed is audit_logger
    assert getattr(app.state, AUDIT_STATE_KEY) is audit_logger
    assert getattr(app.state, AUDIT_INSTALLATION_STATE_KEY) is True


def test_install_returns_same_logger(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    first = install_configuration_api_security_audit(app, audit_logger)
    second = install_configuration_api_security_audit(app, audit_logger)

    assert first is second


def test_get_returns_installed_logger(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    assert (
        get_configuration_api_security_audit_logger(app)
        is audit_logger
    )


def test_get_raises_when_logger_not_installed(app: FastAPI) -> None:
    with pytest.raises(SecurityAuditIntegrationError):
        get_configuration_api_security_audit_logger(app)


def test_installed_status_is_false_before_installation(
    app: FastAPI,
) -> None:
    assert is_configuration_api_security_audit_installed(app) is False


def test_installed_status_is_true_after_installation(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    assert is_configuration_api_security_audit_installed(app) is True


def test_install_rejects_non_fastapi_application(
    audit_logger: SecurityAuditLogger,
) -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit(
            object(),  # type: ignore[arg-type]
            audit_logger,
        )


def test_install_rejects_invalid_logger(app: FastAPI) -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit(
            app,
            object(),  # type: ignore[arg-type]
        )


def test_get_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_logger(
            object()  # type: ignore[arg-type]
        )


def test_status_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        is_configuration_api_security_audit_installed(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Duplicate registration and replacement
# ---------------------------------------------------------------------------


def test_install_rejects_different_existing_logger(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    first = SecurityAuditLogger(tmp_path / "first.jsonl")
    second = SecurityAuditLogger(tmp_path / "second.jsonl")

    try:
        install_configuration_api_security_audit(app, first)

        with pytest.raises(SecurityAuditIntegrationError):
            install_configuration_api_security_audit(app, second)

        assert (
            get_configuration_api_security_audit_logger(app)
            is first
        )
    finally:
        first.close()
        second.close()


def test_install_can_replace_existing_logger(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    first = SecurityAuditLogger(tmp_path / "first.jsonl")
    second = SecurityAuditLogger(tmp_path / "second.jsonl")

    try:
        install_configuration_api_security_audit(app, first)

        installed = install_configuration_api_security_audit(
            app,
            second,
            replace_existing=True,
        )

        assert installed is second
        assert (
            get_configuration_api_security_audit_logger(app)
            is second
        )
    finally:
        first.close()
        second.close()


def test_replacing_logger_does_not_close_previous_logger(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    first = SecurityAuditLogger(tmp_path / "first.jsonl")
    second = SecurityAuditLogger(tmp_path / "second.jsonl")

    try:
        install_configuration_api_security_audit(app, first)
        install_configuration_api_security_audit(
            app,
            second,
            replace_existing=True,
        )

        first.record_event(
            SecurityAuditEventType.REQUEST_REJECTED,
            reason="old_logger_still_open",
        )

        assert len(first.read_events()) == 1
    finally:
        first.close()
        second.close()


# ---------------------------------------------------------------------------
# Generic event recording
# ---------------------------------------------------------------------------


def test_record_security_audit_event(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    audit_log_path: Path,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    event = record_security_audit_event(
        app,
        SecurityAuditEventType.REQUEST_REJECTED,
        principal_id="admin-1",
        success=False,
        reason="invalid_request",
        path="/api/v1/configuration",
        method="POST",
        source_ip="192.0.2.10",
        metadata={"request_id": "request-1"},
    )

    records = read_records(audit_log_path)

    assert event.event_type is SecurityAuditEventType.REQUEST_REJECTED
    assert event.success is False
    assert len(records) == 1

    record = records[0]
    assert record["principal_id"] == "admin-1"
    assert record["metadata"]["reason"] == "invalid_request"
    assert record["metadata"]["path"] == "/api/v1/configuration"
    assert record["metadata"]["method"] == "POST"
    assert record["metadata"]["source_ip"] == "192.0.2.10"
    assert record["metadata"]["request_id"] == "request-1"


def test_record_security_audit_event_requires_installation(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditIntegrationError):
        record_security_audit_event(
            app,
            SecurityAuditEventType.REQUEST_REJECTED,
        )


def test_record_security_audit_event_preserves_metadata(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    record_security_audit_event(
        app,
        SecurityAuditEventType.CONFIGURATION_CHANGED,
        metadata={
            "operation": "update",
            "configuration_id": "config-1",
        },
    )

    record = audit_logger.read_events()[0]

    assert record["metadata"]["operation"] == "update"
    assert record["metadata"]["configuration_id"] == "config-1"


def test_record_security_audit_event_redacts_secrets(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    record_security_audit_event(
        app,
        SecurityAuditEventType.AUTHENTICATION_FAILURE,
        metadata={
            "password": "do-not-store",
            "api_key": "sensitive-key",
        },
    )

    record = audit_logger.read_events()[0]

    assert record["metadata"]["password"] == "[REDACTED]"
    assert record["metadata"]["api_key"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("success", "expected_type"),
    [
        (
            True,
            SecurityAuditEventType.AUTHENTICATION_SUCCESS,
        ),
        (
            False,
            SecurityAuditEventType.AUTHENTICATION_FAILURE,
        ),
    ],
)
def test_record_authentication_result(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    success: bool,
    expected_type: SecurityAuditEventType,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    event = record_authentication_result(
        app,
        success=success,
        principal_id="admin-1" if success else None,
        reason=None if success else "invalid_credentials",
        source_ip="192.0.2.20",
        metadata={"mechanism": "session"},
    )

    assert event.event_type is expected_type
    assert event.success is success

    record = audit_logger.read_events()[0]
    assert record["metadata"]["source_ip"] == "192.0.2.20"
    assert record["metadata"]["mechanism"] == "session"


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("success", "expected_type"),
    [
        (
            True,
            SecurityAuditEventType.AUTHORIZATION_SUCCESS,
        ),
        (
            False,
            SecurityAuditEventType.AUTHORIZATION_FAILURE,
        ),
    ],
)
def test_record_authorization_result(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    success: bool,
    expected_type: SecurityAuditEventType,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    event = record_authorization_result(
        app,
        success=success,
        principal_id="operator-1",
        permission="UPDATE_CONFIGURATION",
        resource="configuration-1",
        reason=None if success else "permission_denied",
        metadata={"role": "OPERATOR"},
    )

    assert event.event_type is expected_type
    assert event.success is success

    record = audit_logger.read_events()[0]
    assert record["metadata"]["permission"] == "UPDATE_CONFIGURATION"
    assert record["metadata"]["resource"] == "configuration-1"
    assert record["metadata"]["role"] == "OPERATOR"


# ---------------------------------------------------------------------------
# Rate-limit and request-rejection helpers
# ---------------------------------------------------------------------------


def test_record_rate_limit_rejection(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    event = record_rate_limit_rejection(
        app,
        principal_id="operator-1",
        path="/api/v1/configuration",
        method="POST",
        source_ip="192.0.2.30",
        metadata={"limit": 20},
    )

    assert event.event_type is SecurityAuditEventType.RATE_LIMIT_REJECTED
    assert event.success is False

    record = audit_logger.read_events()[0]
    assert record["metadata"]["reason"] == "rate_limit_exceeded"
    assert record["metadata"]["path"] == "/api/v1/configuration"
    assert record["metadata"]["method"] == "POST"
    assert record["metadata"]["limit"] == 20


def test_record_request_rejection(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    event = record_request_rejection(
        app,
        reason="payload_too_large",
        principal_id="admin-1",
        path="/api/v1/configuration/import",
        method="POST",
        source_ip="192.0.2.40",
        metadata={"maximum_bytes": 1048576},
    )

    assert event.event_type is SecurityAuditEventType.REQUEST_REJECTED
    assert event.success is False

    record = audit_logger.read_events()[0]
    assert record["metadata"]["reason"] == "payload_too_large"
    assert record["metadata"]["maximum_bytes"] == 1048576


def test_request_rejection_requires_reason(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    with pytest.raises((TypeError, ValueError)):
        record_request_rejection(
            app,
            reason="",
        )


# ---------------------------------------------------------------------------
# Removal and lifecycle
# ---------------------------------------------------------------------------


def test_remove_unregisters_logger(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    removed = remove_configuration_api_security_audit(app)

    assert removed is audit_logger
    assert is_configuration_api_security_audit_installed(app) is False
    assert getattr(app.state, AUDIT_INSTALLATION_STATE_KEY) is False

    with pytest.raises(SecurityAuditIntegrationError):
        get_configuration_api_security_audit_logger(app)


def test_remove_does_not_close_logger_by_default(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    remove_configuration_api_security_audit(app)

    event = audit_logger.record_event(
        SecurityAuditEventType.REQUEST_REJECTED,
        reason="logger_remains_open",
    )

    assert event.event_type is SecurityAuditEventType.REQUEST_REJECTED


def test_remove_can_close_logger(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    logger = SecurityAuditLogger(tmp_path / "security.jsonl")
    install_configuration_api_security_audit(app, logger)

    removed = remove_configuration_api_security_audit(
        app,
        close_logger=True,
    )

    assert removed is logger

    with pytest.raises(RuntimeError):
        logger.record_event(
            SecurityAuditEventType.REQUEST_REJECTED,
            reason="must_fail",
        )


def test_remove_rejects_when_not_installed(app: FastAPI) -> None:
    with pytest.raises(SecurityAuditIntegrationError):
        remove_configuration_api_security_audit(app)


def test_uninstalled_logger_can_be_registered_again(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)
    remove_configuration_api_security_audit(app)

    installed = install_configuration_api_security_audit(
        app,
        audit_logger,
    )

    assert installed is audit_logger
    assert is_configuration_api_security_audit_installed(app) is True


# ---------------------------------------------------------------------------
# Integration state isolation
# ---------------------------------------------------------------------------


def test_two_applications_can_use_different_audit_loggers(
    tmp_path: Path,
) -> None:
    first_app = FastAPI()
    second_app = FastAPI()

    first_logger = SecurityAuditLogger(tmp_path / "first.jsonl")
    second_logger = SecurityAuditLogger(tmp_path / "second.jsonl")

    try:
        install_configuration_api_security_audit(
            first_app,
            first_logger,
        )
        install_configuration_api_security_audit(
            second_app,
            second_logger,
        )

        record_authentication_result(
            first_app,
            success=True,
            principal_id="first-admin",
        )
        record_authentication_result(
            second_app,
            success=False,
            principal_id=None,
        )

        assert len(first_logger.read_events()) == 1
        assert len(second_logger.read_events()) == 1

        assert (
            first_logger.read_events()[0]["principal_id"]
            == "first-admin"
        )
        assert (
            second_logger.read_events()[0]["success"]
            is False
        )
    finally:
        first_logger.close()
        second_logger.close()


def test_recorded_event_contains_timezone_aware_timestamp(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit(app, audit_logger)

    record_authentication_result(
        app,
        success=True,
        principal_id="admin-1",
    )

    record = audit_logger.read_events()[0]
    timestamp = datetime.fromisoformat(record["occurred_at"])

    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() is not None
