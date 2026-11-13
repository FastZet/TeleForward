
"""Tests for configuration API security audit health monitoring."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.services.scheduling.configuration_api_security_audit import (
    SecurityAuditEventType,
    SecurityAuditLogger,
)
from app.services.scheduling.configuration_api_security_audit_health import (
    AuditHealthCheckResult,
    AuditHealthCheckStatus,
    AuditHealthReport,
    AuditHealthStatus,
    SecurityAuditHealthService,
)


UTC = timezone.utc


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


def make_service(
    audit_logger: SecurityAuditLogger | None,
    audit_path: Path | None = None,
) -> SecurityAuditHealthService:
    return SecurityAuditHealthService(
        audit_logger,
        audit_file_path=audit_path,
    )


# ---------------------------------------------------------------------------
# Health result models
# ---------------------------------------------------------------------------


def test_health_check_result_accepts_valid_values() -> None:
    result = AuditHealthCheckResult(
        name="logger",
        status=AuditHealthCheckStatus.PASSED,
        message="Logger available",
        checked_at=datetime.now(UTC),
        details={"available": True},
    )

    assert result.name == "logger"
    assert result.status is AuditHealthCheckStatus.PASSED
    assert result.details["available"] is True


def test_health_check_result_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        AuditHealthCheckResult(
            name=" ",
            status=AuditHealthCheckStatus.PASSED,
            message="OK",
            checked_at=datetime.now(UTC),
            details={},
        )


def test_health_check_result_rejects_invalid_status() -> None:
    with pytest.raises(TypeError):
        AuditHealthCheckResult(
            name="logger",
            status="passed",  # type: ignore[arg-type]
            message="OK",
            checked_at=datetime.now(UTC),
            details={},
        )


def test_health_check_result_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        AuditHealthCheckResult(
            name="logger",
            status=AuditHealthCheckStatus.PASSED,
            message="OK",
            checked_at=datetime(2026, 11, 13, 10, 0),
            details={},
        )


def test_health_check_result_copies_details() -> None:
    details = {"available": True}

    result = AuditHealthCheckResult(
        name="logger",
        status=AuditHealthCheckStatus.PASSED,
        message="OK",
        checked_at=datetime.now(UTC),
        details=details,
    )

    details["available"] = False

    assert result.details["available"] is True


def test_health_report_accepts_valid_values() -> None:
    check = AuditHealthCheckResult(
        name="logger",
        status=AuditHealthCheckStatus.PASSED,
        message="Available",
        checked_at=datetime.now(UTC),
        details={},
    )

    report = AuditHealthReport(
        status=AuditHealthStatus.HEALTHY,
        checked_at=datetime.now(UTC),
        checks=(check,),
        logger_available=True,
    )

    assert report.healthy is True
    assert report.failed_checks == ()
    assert report.warning_checks == ()


def test_health_report_rejects_invalid_status() -> None:
    with pytest.raises(TypeError):
        AuditHealthReport(
            status="healthy",  # type: ignore[arg-type]
            checked_at=datetime.now(UTC),
            checks=(),
            logger_available=True,
        )


def test_health_report_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        AuditHealthReport(
            status=AuditHealthStatus.HEALTHY,
            checked_at=datetime(2026, 11, 13, 10, 0),
            checks=(),
            logger_available=True,
        )


def test_health_report_rejects_non_tuple_checks() -> None:
    with pytest.raises(TypeError):
        AuditHealthReport(
            status=AuditHealthStatus.HEALTHY,
            checked_at=datetime.now(UTC),
            checks=[],  # type: ignore[arg-type]
            logger_available=True,
        )


def test_health_report_rejects_invalid_check_items() -> None:
    with pytest.raises(TypeError):
        AuditHealthReport(
            status=AuditHealthStatus.HEALTHY,
            checked_at=datetime.now(UTC),
            checks=("invalid",),  # type: ignore[arg-type]
            logger_available=True,
        )


def test_health_report_rejects_non_boolean_logger_availability() -> None:
    with pytest.raises(TypeError):
        AuditHealthReport(
            status=AuditHealthStatus.HEALTHY,
            checked_at=datetime.now(UTC),
            checks=(),
            logger_available=1,  # type: ignore[arg-type]
        )


def test_report_to_dict_returns_json_compatible_structure() -> None:
    checked_at = datetime.now(UTC)
    check = AuditHealthCheckResult(
        name="storage",
        status=AuditHealthCheckStatus.PASSED,
        message="Accessible",
        checked_at=checked_at,
        details={"writable": True},
    )

    report = AuditHealthReport(
        status=AuditHealthStatus.HEALTHY,
        checked_at=checked_at,
        checks=(check,),
        logger_available=True,
    )

    result = report.to_dict()

    assert result["status"] == "healthy"
    assert result["healthy"] is True
    assert result["logger_available"] is True
    assert result["checks"][0]["name"] == "storage"
    assert result["checks"][0]["details"]["writable"] is True


def test_report_failed_checks_property() -> None:
    checks = (
        AuditHealthCheckResult(
            name="logger",
            status=AuditHealthCheckStatus.PASSED,
            message="Available",
            checked_at=datetime.now(UTC),
            details={},
        ),
        AuditHealthCheckResult(
            name="integrity",
            status=AuditHealthCheckStatus.FAILED,
            message="Invalid records",
            checked_at=datetime.now(UTC),
            details={},
        ),
    )

    report = AuditHealthReport(
        status=AuditHealthStatus.UNHEALTHY,
        checked_at=datetime.now(UTC),
        checks=checks,
        logger_available=True,
    )

    assert [item.name for item in report.failed_checks] == ["integrity"]


def test_report_warning_checks_property() -> None:
    check = AuditHealthCheckResult(
        name="storage",
        status=AuditHealthCheckStatus.WARNING,
        message="Warning",
        checked_at=datetime.now(UTC),
        details={},
    )

    report = AuditHealthReport(
        status=AuditHealthStatus.DEGRADED,
        checked_at=datetime.now(UTC),
        checks=(check,),
        logger_available=True,
    )

    assert report.warning_checks == (check,)


# ---------------------------------------------------------------------------
# Service construction
# ---------------------------------------------------------------------------


def test_service_accepts_valid_logger(
    audit_logger: SecurityAuditLogger,
) -> None:
    service = SecurityAuditHealthService(audit_logger)

    assert service is not None


def test_service_accepts_missing_logger() -> None:
    service = SecurityAuditHealthService(None)

    assert service is not None


def test_service_rejects_invalid_logger() -> None:
    with pytest.raises(TypeError):
        SecurityAuditHealthService(object())  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_path", ["", " ", 123, object()])
def test_service_rejects_invalid_path(
    audit_logger: SecurityAuditLogger,
    invalid_path: Any,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        SecurityAuditHealthService(
            audit_logger,
            audit_file_path=invalid_path,
        )


# ---------------------------------------------------------------------------
# Healthy logger
# ---------------------------------------------------------------------------


def test_healthy_logger_produces_healthy_report(
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    service = make_service(audit_logger, audit_path)

    report = service.check()

    assert report.status is AuditHealthStatus.HEALTHY
    assert report.healthy is True
    assert report.logger_available is True

    statuses = {
        check.name: check.status
        for check in report.checks
    }

    assert statuses["logger"] is AuditHealthCheckStatus.PASSED
    assert statuses["storage_path"] is AuditHealthCheckStatus.PASSED
    assert statuses["storage_permissions"] is AuditHealthCheckStatus.PASSED
    assert statuses["audit_integrity"] is AuditHealthCheckStatus.PASSED


def test_health_check_does_not_append_audit_events(
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    audit_logger.record_event(
        SecurityAuditEventType.AUTHENTICATION_SUCCESS,
        principal_id="admin-1",
    )

    before = audit_path.read_bytes()
    report = make_service(audit_logger, audit_path).check()
    after = audit_path.read_bytes()

    assert report.healthy is True
    assert before == after


def test_health_report_has_timezone_aware_timestamps(
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    report = make_service(audit_logger, audit_path).check()

    assert report.checked_at.tzinfo is not None

    for check in report.checks:
        assert check.checked_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Missing logger
# ---------------------------------------------------------------------------


def test_missing_logger_produces_unhealthy_report() -> None:
    report = SecurityAuditHealthService(None).check()

    assert report.status is AuditHealthStatus.UNHEALTHY
    assert report.logger_available is False

    logger_check = next(
        check for check in report.checks
        if check.name == "logger"
    )

    assert logger_check.status is AuditHealthCheckStatus.FAILED


def test_missing_logger_skips_storage_checks() -> None:
    report = SecurityAuditHealthService(None).check()

    statuses = {
        check.name: check.status
        for check in report.checks
    }

    assert statuses["storage_path"] is AuditHealthCheckStatus.SKIPPED
    assert statuses["storage_permissions"] is AuditHealthCheckStatus.SKIPPED
    assert statuses["audit_integrity"] is AuditHealthCheckStatus.SKIPPED


# ---------------------------------------------------------------------------
# Closed logger
# ---------------------------------------------------------------------------


def test_closed_logger_produces_unhealthy_report(
    audit_path: Path,
) -> None:
    audit_logger = SecurityAuditLogger(audit_path, fsync=False)
    audit_logger.close()

    report = SecurityAuditHealthService(
        audit_logger,
        audit_file_path=audit_path,
    ).check()

    assert report.status is AuditHealthStatus.UNHEALTHY
    assert report.logger_available is False

    logger_check = next(
        check for check in report.checks
        if check.name == "logger"
    )

    assert logger_check.status is AuditHealthCheckStatus.FAILED


# ---------------------------------------------------------------------------
# Storage path checks
# ---------------------------------------------------------------------------


def test_missing_storage_directory_is_unhealthy(
    audit_logger: SecurityAuditLogger,
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing" / "security.jsonl"

    report = make_service(
        audit_logger,
        missing_path,
    ).check()

    storage_check = next(
        check for check in report.checks
        if check.name == "storage_path"
    )

    assert storage_check.status is AuditHealthCheckStatus.FAILED
    assert report.status is AuditHealthStatus.UNHEALTHY


def test_directory_used_as_audit_file_is_unhealthy(
    audit_logger: SecurityAuditLogger,
    tmp_path: Path,
) -> None:
    directory_path = tmp_path / "audit-directory"
    directory_path.mkdir()

    report = make_service(
        audit_logger,
        directory_path,
    ).check()

    storage_check = next(
        check for check in report.checks
        if check.name == "storage_path"
    )

    assert storage_check.status is AuditHealthCheckStatus.FAILED


def test_explicit_path_takes_precedence_over_logger_path(
    audit_logger: SecurityAuditLogger,
    tmp_path: Path,
) -> None:
    explicit_path = tmp_path / "other" / "security.jsonl"

    report = make_service(
        audit_logger,
        explicit_path,
    ).check()

    storage_check = next(
        check for check in report.checks
        if check.name == "storage_path"
    )

    assert storage_check.status is AuditHealthCheckStatus.FAILED


# ---------------------------------------------------------------------------
# Permission checks
# ---------------------------------------------------------------------------


def test_permission_check_reports_readable_and_writable_storage(
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    report = make_service(audit_logger, audit_path).check()

    permission_check = next(
        check for check in report.checks
        if check.name == "storage_permissions"
    )

    assert permission_check.status is AuditHealthCheckStatus.PASSED
    assert permission_check.details["readable"] is True
    assert permission_check.details["writable"] is True


def test_permission_check_failure_is_reported(
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        os,
        "access",
        lambda path, mode: mode == os.R_OK,
    )

    report = make_service(audit_logger, audit_path).check()

    permission_check = next(
        check for check in report.checks
        if check.name == "storage_permissions"
    )

    assert permission_check.status is AuditHealthCheckStatus.FAILED
    assert report.status is AuditHealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# Audit integrity
# ---------------------------------------------------------------------------


def test_integrity_check_passes_for_valid_records(
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    audit_logger.record_event(
        SecurityAuditEventType.AUTHENTICATION_SUCCESS,
        principal_id="admin-1",
    )

    report = make_service(audit_logger, audit_path).check()

    integrity_check = next(
        check for check in report.checks
        if check.name == "audit_integrity"
    )

    assert integrity_check.status is AuditHealthCheckStatus.PASSED
    assert integrity_check.details["recent_records_read"] == 1


def test_integrity_check_fails_for_malformed_json(
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    audit_path.write_text(
        "{malformed json}\n",
        encoding="utf-8",
    )

    report = make_service(audit_logger, audit_path).check()

    integrity_check = next(
        check for check in report.checks
        if check.name == "audit_integrity"
    )

    assert integrity_check.status is AuditHealthCheckStatus.FAILED
    assert report.status is AuditHealthStatus.UNHEALTHY


def test_integrity_check_passes_for_empty_log(
    audit_logger: SecurityAuditLogger,
    audit_path: Path,
) -> None:
    report = make_service(audit_logger, audit_path).check()

    integrity_check = next(
        check for check in report.checks
        if check.name == "audit_integrity"
    )

    assert integrity_check.status is AuditHealthCheckStatus.PASSED
    assert integrity_check.details["recent_records_read"] == 0


# ---------------------------------------------------------------------------
# Overall status aggregation
# ---------------------------------------------------------------------------


def test_failed_check_produces_unhealthy_status() -> None:
    checks = (
        AuditHealthCheckResult(
            name="logger",
            status=AuditHealthCheckStatus.PASSED,
            message="Available",
            checked_at=datetime.now(UTC),
            details={},
        ),
        AuditHealthCheckResult(
            name="integrity",
            status=AuditHealthCheckStatus.FAILED,
            message="Invalid log",
            checked_at=datetime.now(UTC),
            details={},
        ),
    )

    report = AuditHealthReport(
        status=AuditHealthStatus.UNHEALTHY,
        checked_at=datetime.now(UTC),
        checks=checks,
        logger_available=True,
    )

    assert report.healthy is False
    assert report.status is AuditHealthStatus.UNHEALTHY


def test_warning_check_produces_degraded_status() -> None:
    checks = (
        AuditHealthCheckResult(
            name="logger",
            status=AuditHealthCheckStatus.PASSED,
            message="Available",
            checked_at=datetime.now(UTC),
            details={},
        ),
        AuditHealthCheckResult(
            name="storage",
            status=AuditHealthCheckStatus.WARNING,
            message="Storage warning",
            checked_at=datetime.now(UTC),
            details={},
        ),
    )

    report = AuditHealthReport(
        status=AuditHealthStatus.DEGRADED,
        checked_at=datetime.now(UTC),
        checks=checks,
        logger_available=True,
    )

    assert report.healthy is False
    assert report.status is AuditHealthStatus.DEGRADED


def test_skipped_check_produces_degraded_status() -> None:
    checks = (
        AuditHealthCheckResult(
            name="logger",
            status=AuditHealthCheckStatus.PASSED,
            message="Available",
            checked_at=datetime.now(UTC),
            details={},
        ),
        AuditHealthCheckResult(
            name="storage",
            status=AuditHealthCheckStatus.SKIPPED,
            message="Not configured",
            checked_at=datetime.now(UTC),
            details={},
        ),
    )

    report = AuditHealthReport(
        status=AuditHealthStatus.DEGRADED,
        checked_at=datetime.now(UTC),
        checks=checks,
        logger_available=True,
    )

    assert report.status is AuditHealthStatus.DEGRADED
