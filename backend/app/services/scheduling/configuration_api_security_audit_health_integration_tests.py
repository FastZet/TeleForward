
"""Integration tests for security audit health monitoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditEventType,
    SecurityAuditLogger,
)
from app.services.scheduling.configuration_api_security_audit_health import (
    AuditHealthReport,
    AuditHealthStatus,
    SecurityAuditHealthService,
)
from app.services.scheduling.configuration_api_security_audit_health_integration import (
    HEALTH_INSTALLATION_STATE_KEY,
    HEALTH_SERVICE_STATE_KEY,
    SecurityAuditHealthIntegrationError,
    check_configuration_api_security_audit_health,
    get_configuration_api_security_audit_health_service,
    get_configuration_api_security_audit_health_status,
    install_configuration_api_security_audit_health,
    is_configuration_api_security_audit_health_installed,
    remove_configuration_api_security_audit_health,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


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


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def test_install_registers_health_service(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    service = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
        audit_file_path=str(audit_path),
    )

    assert isinstance(service, SecurityAuditHealthService)
    assert (
        getattr(app.state, HEALTH_SERVICE_STATE_KEY)
        is service
    )
    assert getattr(app.state, HEALTH_INSTALLATION_STATE_KEY) is True


def test_install_returns_registered_service(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    service = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    assert (
        get_configuration_api_security_audit_health_service(app)
        is service
    )


def test_install_accepts_missing_logger(
    app: FastAPI,
) -> None:
    service = install_configuration_api_security_audit_health(app)

    assert isinstance(service, SecurityAuditHealthService)


def test_install_accepts_explicit_storage_path(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    service = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
        audit_file_path=str(audit_path),
    )

    report = service.check()

    assert report.status is AuditHealthStatus.HEALTHY


def test_install_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit_health(
            object(),  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_logger(
    app: FastAPI,
) -> None:
    with pytest.raises(TypeError):
        install_configuration_api_security_audit_health(
            app,
            audit_logger=object(),  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_path(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        install_configuration_api_security_audit_health(
            app,
            audit_logger=audit_logger,
            audit_file_path=" ",
        )


# ---------------------------------------------------------------------------
# Duplicate registration and replacement
# ---------------------------------------------------------------------------


def test_duplicate_installation_is_rejected(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    first = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    with pytest.raises(SecurityAuditHealthIntegrationError):
        install_configuration_api_security_audit_health(
            app,
            audit_logger=audit_logger,
        )

    assert (
        get_configuration_api_security_audit_health_service(app)
        is first
    )


def test_replacement_is_rejected_by_default(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    first = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    with pytest.raises(SecurityAuditHealthIntegrationError):
        install_configuration_api_security_audit_health(
            app,
            audit_logger=audit_logger,
            replace_existing=False,
        )

    assert (
        get_configuration_api_security_audit_health_service(app)
        is first
    )


def test_replacement_creates_new_service(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    first = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    second = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
        audit_file_path=str(audit_path),
        replace_existing=True,
    )

    assert second is not first
    assert isinstance(second, SecurityAuditHealthService)
    assert (
        get_configuration_api_security_audit_health_service(app)
        is second
    )


def test_replacement_does_not_close_shared_logger(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
        replace_existing=True,
    )

    event = audit_logger.record_event(
        SecurityAuditEventType.REQUEST_REJECTED,
        reason="logger_still_open",
    )

    assert event.event_type is SecurityAuditEventType.REQUEST_REJECTED


# ---------------------------------------------------------------------------
# Installation status and accessors
# ---------------------------------------------------------------------------


def test_status_is_false_before_installation(
    app: FastAPI,
) -> None:
    assert (
        is_configuration_api_security_audit_health_installed(app)
        is False
    )


def test_status_is_true_after_installation(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    assert (
        is_configuration_api_security_audit_health_installed(app)
        is True
    )


def test_get_service_raises_before_installation(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthIntegrationError):
        get_configuration_api_security_audit_health_service(app)


def test_accessors_reject_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        get_configuration_api_security_audit_health_service(
            object()  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError):
        is_configuration_api_security_audit_health_installed(
            object()  # type: ignore[arg-type]
        )


def test_invalid_service_state_is_rejected(
    app: FastAPI,
) -> None:
    setattr(app.state, HEALTH_SERVICE_STATE_KEY, object())

    assert (
        is_configuration_api_security_audit_health_installed(app)
        is False
    )

    with pytest.raises(SecurityAuditHealthIntegrationError):
        get_configuration_api_security_audit_health_service(app)


def test_install_rejects_invalid_existing_service_state(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    setattr(app.state, HEALTH_SERVICE_STATE_KEY, object())

    with pytest.raises(SecurityAuditHealthIntegrationError):
        install_configuration_api_security_audit_health(
            app,
            audit_logger=audit_logger,
        )


# ---------------------------------------------------------------------------
# Health-check execution
# ---------------------------------------------------------------------------


def test_check_executes_registered_health_service(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
        audit_file_path=str(audit_path),
    )

    report = check_configuration_api_security_audit_health(app)

    assert isinstance(report, AuditHealthReport)
    assert report.status is AuditHealthStatus.HEALTHY
    assert report.logger_available is True


def test_check_returns_unhealthy_report_without_logger(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health(app)

    report = check_configuration_api_security_audit_health(app)

    assert report.status is AuditHealthStatus.UNHEALTHY
    assert report.logger_available is False


def test_check_requires_installed_service(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthIntegrationError):
        check_configuration_api_security_audit_health(app)


def test_check_wraps_unexpected_service_errors(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    def fail() -> AuditHealthReport:
        raise OSError("simulated health-check failure")

    monkeypatch.setattr(service, "check", fail)

    with pytest.raises(
        SecurityAuditHealthIntegrationError,
        match="Could not execute",
    ):
        check_configuration_api_security_audit_health(app)


def test_check_preserves_original_exception_as_cause(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    def fail() -> AuditHealthReport:
        raise OSError("storage unavailable")

    monkeypatch.setattr(service, "check", fail)

    with pytest.raises(SecurityAuditHealthIntegrationError) as exc_info:
        check_configuration_api_security_audit_health(app)

    assert isinstance(exc_info.value.__cause__, OSError)


# ---------------------------------------------------------------------------
# Status serialization
# ---------------------------------------------------------------------------


def test_status_returns_serializable_health_report(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
        audit_file_path=str(audit_path),
    )

    result = get_configuration_api_security_audit_health_status(app)

    assert isinstance(result, dict)
    assert result["status"] == "healthy"
    assert result["healthy"] is True
    assert result["logger_available"] is True
    assert isinstance(result["checks"], list)


def test_status_returns_unhealthy_when_logger_missing(
    app: FastAPI,
) -> None:
    install_configuration_api_security_audit_health(app)

    result = get_configuration_api_security_audit_health_status(app)

    assert result["status"] == "unhealthy"
    assert result["healthy"] is False
    assert result["logger_available"] is False


def test_status_requires_installed_service(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthIntegrationError):
        get_configuration_api_security_audit_health_status(app)


def test_status_wraps_health_check_failure(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    def fail() -> AuditHealthReport:
        raise RuntimeError("health check failed")

    monkeypatch.setattr(service, "check", fail)

    with pytest.raises(SecurityAuditHealthIntegrationError):
        get_configuration_api_security_audit_health_status(app)


# ---------------------------------------------------------------------------
# Removal and lifecycle
# ---------------------------------------------------------------------------


def test_remove_unregisters_health_service(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    service = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    removed = remove_configuration_api_security_audit_health(app)

    assert removed is service
    assert (
        is_configuration_api_security_audit_health_installed(app)
        is False
    )
    assert getattr(app.state, HEALTH_INSTALLATION_STATE_KEY) is False


def test_remove_does_not_close_audit_logger(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    remove_configuration_api_security_audit_health(app)

    event = audit_logger.record_event(
        SecurityAuditEventType.REQUEST_REJECTED,
        reason="logger_remains_open",
    )

    assert event.event_type is SecurityAuditEventType.REQUEST_REJECTED


def test_remove_requires_installed_service(
    app: FastAPI,
) -> None:
    with pytest.raises(SecurityAuditHealthIntegrationError):
        remove_configuration_api_security_audit_health(app)


def test_removed_service_can_be_reinstalled(
    app: FastAPI,
    audit_logger: SecurityAuditLogger,
) -> None:
    first = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    remove_configuration_api_security_audit_health(app)

    second = install_configuration_api_security_audit_health(
        app,
        audit_logger=audit_logger,
    )

    assert first is not second
    assert (
        get_configuration_api_security_audit_health_service(app)
        is second
    )


def test_remove_rejects_non_fastapi_application() -> None:
    with pytest.raises(TypeError):
        remove_configuration_api_security_audit_health(
            object()  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Application isolation
# ---------------------------------------------------------------------------


def test_applications_have_independent_health_services(
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
        first_service = install_configuration_api_security_audit_health(
            first_app,
            audit_logger=first_logger,
        )
        second_service = install_configuration_api_security_audit_health(
            second_app,
            audit_logger=second_logger,
        )

        assert first_service is not second_service
        assert (
            get_configuration_api_security_audit_health_service(first_app)
            is first_service
        )
        assert (
            get_configuration_api_security_audit_health_service(second_app)
            is second_service
        )
    finally:
        first_logger.close()
        second_logger.close()
