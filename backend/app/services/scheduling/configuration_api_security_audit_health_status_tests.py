
"""Tests for consolidated security audit health status."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.scheduling.configuration_api_security_audit_health import (
    AuditHealthCheckResult,
    AuditHealthReport,
    AuditHealthStatus,
)
from app.services.scheduling.configuration_api_security_audit_health_status import (
    SecurityAuditComponentHealth,
    SecurityAuditComponentStatus,
    SecurityAuditHealthStatusBuilder,
    SecurityAuditSubsystemHealth,
    SecurityAuditSubsystemStatus,
    build_security_audit_health_status,
)


@pytest.fixture
def healthy_report() -> AuditHealthReport:
    return AuditHealthReport(
        status=AuditHealthStatus.HEALTHY,
        checked_at=datetime.now(timezone.utc),
        checks=(
            AuditHealthCheckResult(
                name="logger_available",
                passed=True,
                message="Audit logger is available",
            ),
        ),
        logger_available=True,
    )


@pytest.fixture
def unhealthy_report() -> AuditHealthReport:
    return AuditHealthReport(
        status=AuditHealthStatus.UNHEALTHY,
        checked_at=datetime.now(timezone.utc),
        checks=(
            AuditHealthCheckResult(
                name="logger_available",
                passed=False,
                message="Audit logger is unavailable",
            ),
        ),
        logger_available=False,
    )


# ---------------------------------------------------------------------------
# Component model
# ---------------------------------------------------------------------------


def test_component_health_accepts_valid_values() -> None:
    component = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.HEALTHY,
        message="Logger is available",
        details={"available": True},
    )

    assert component.name == "audit_logger"
    assert component.status is SecurityAuditComponentStatus.HEALTHY
    assert component.message == "Logger is available"
    assert component.details["available"] is True


def test_component_name_is_normalized() -> None:
    component = SecurityAuditComponentHealth(
        name="  audit_logger  ",
        status=SecurityAuditComponentStatus.HEALTHY,
    )

    assert component.name == "audit_logger"


@pytest.mark.parametrize("name", ["", " ", "\t"])
def test_component_rejects_empty_name(name: str) -> None:
    with pytest.raises(ValueError):
        SecurityAuditComponentHealth(
            name=name,
            status=SecurityAuditComponentStatus.HEALTHY,
        )


def test_component_rejects_invalid_name_type() -> None:
    with pytest.raises(ValueError):
        SecurityAuditComponentHealth(
            name=123,  # type: ignore[arg-type]
            status=SecurityAuditComponentStatus.HEALTHY,
        )


def test_component_rejects_invalid_status() -> None:
    with pytest.raises(TypeError):
        SecurityAuditComponentHealth(
            name="audit_logger",
            status="healthy",  # type: ignore[arg-type]
        )


def test_component_rejects_invalid_message() -> None:
    with pytest.raises(TypeError):
        SecurityAuditComponentHealth(
            name="audit_logger",
            status=SecurityAuditComponentStatus.HEALTHY,
            message=123,  # type: ignore[arg-type]
        )


def test_component_rejects_non_mapping_details() -> None:
    with pytest.raises(TypeError):
        SecurityAuditComponentHealth(
            name="audit_logger",
            status=SecurityAuditComponentStatus.HEALTHY,
            details=[],  # type: ignore[arg-type]
        )


def test_component_copies_details_mapping() -> None:
    details = {"available": True}

    component = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.HEALTHY,
        details=details,
    )

    details["available"] = False

    assert component.details["available"] is True


def test_component_to_dict() -> None:
    component = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.DEGRADED,
        message="Logger has warnings",
        details={"warning_count": 2},
    )

    result = component.to_dict()

    assert result == {
        "name": "audit_logger",
        "status": "degraded",
        "message": "Logger has warnings",
        "details": {"warning_count": 2},
    }


def test_component_to_dict_returns_independent_details_mapping() -> None:
    component = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.HEALTHY,
        details={"available": True},
    )

    result = component.to_dict()
    result["details"]["available"] = False

    assert component.details["available"] is True


# ---------------------------------------------------------------------------
# Consolidated health model
# ---------------------------------------------------------------------------


def test_subsystem_health_accepts_valid_values() -> None:
    checked_at = datetime.now(timezone.utc)

    component = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.HEALTHY,
    )

    health = SecurityAuditSubsystemHealth(
        status=SecurityAuditSubsystemStatus.HEALTHY,
        checked_at=checked_at,
        components=(component,),
    )

    assert health.status is SecurityAuditSubsystemStatus.HEALTHY
    assert health.healthy is True
    assert len(health.components) == 1


def test_subsystem_health_requires_valid_status() -> None:
    with pytest.raises(TypeError):
        SecurityAuditSubsystemHealth(
            status="healthy",  # type: ignore[arg-type]
            checked_at=datetime.now(timezone.utc),
            components=(),
        )


def test_subsystem_health_requires_datetime() -> None:
    with pytest.raises(TypeError):
        SecurityAuditSubsystemHealth(
            status=SecurityAuditSubsystemStatus.HEALTHY,
            checked_at="2026-11-13",  # type: ignore[arg-type]
            components=(),
        )


def test_subsystem_health_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        SecurityAuditSubsystemHealth(
            status=SecurityAuditSubsystemStatus.HEALTHY,
            checked_at=datetime(2026, 11, 13),
            components=(),
        )


def test_subsystem_health_normalizes_timestamp_to_utc() -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime(
        2026, 11, 13, 12, 0, tzinfo=offset
    )

    health = SecurityAuditSubsystemHealth(
        status=SecurityAuditSubsystemStatus.HEALTHY,
        checked_at=timestamp,
        components=(),
    )

    assert health.checked_at.utcoffset() == timedelta(0)
    assert health.checked_at.hour == 6
    assert health.checked_at.minute == 30


def test_subsystem_health_rejects_invalid_component() -> None:
    with pytest.raises(TypeError):
        SecurityAuditSubsystemHealth(
            status=SecurityAuditSubsystemStatus.HEALTHY,
            checked_at=datetime.now(timezone.utc),
            components=(object(),),  # type: ignore[arg-type]
        )


def test_subsystem_health_rejects_duplicate_component_names() -> None:
    first = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.HEALTHY,
    )
    second = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.DEGRADED,
    )

    with pytest.raises(ValueError):
        SecurityAuditSubsystemHealth(
            status=SecurityAuditSubsystemStatus.DEGRADED,
            checked_at=datetime.now(timezone.utc),
            components=(first, second),
        )


def test_subsystem_health_rejects_non_string_messages() -> None:
    with pytest.raises(TypeError):
        SecurityAuditSubsystemHealth(
            status=SecurityAuditSubsystemStatus.HEALTHY,
            checked_at=datetime.now(timezone.utc),
            components=(),
            messages=(123,),  # type: ignore[arg-type]
        )


def test_subsystem_health_get_component() -> None:
    component = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.HEALTHY,
    )

    health = SecurityAuditSubsystemHealth(
        status=SecurityAuditSubsystemStatus.HEALTHY,
        checked_at=datetime.now(timezone.utc),
        components=(component,),
    )

    assert health.get_component("audit_logger") is component
    assert health.get_component("missing") is None


def test_subsystem_health_to_dict() -> None:
    component = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.HEALTHY,
        details={"available": True},
    )

    health = SecurityAuditSubsystemHealth(
        status=SecurityAuditSubsystemStatus.HEALTHY,
        checked_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        components=(component,),
    )

    result = health.to_dict()

    assert result["status"] == "healthy"
    assert result["healthy"] is True
    assert result["checked_at"] == "2026-11-13T00:00:00+00:00"
    assert result["components"][0]["name"] == "audit_logger"
    assert result["messages"] == []


def test_healthy_property_is_false_for_non_healthy_status() -> None:
    health = SecurityAuditSubsystemHealth(
        status=SecurityAuditSubsystemStatus.DEGRADED,
        checked_at=datetime.now(timezone.utc),
        components=(),
    )

    assert health.healthy is False


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def test_builder_starts_empty() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    result = builder.build()

    assert result.status is SecurityAuditSubsystemStatus.UNKNOWN
    assert result.components == ()
    assert result.messages == (
        "No health components were registered",
    )


def test_builder_adds_component() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    component = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.HEALTHY,
    )

    builder.add_component(component)

    result = builder.build()

    assert result.get_component("audit_logger") is component


def test_builder_rejects_invalid_component() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    with pytest.raises(TypeError):
        builder.add_component(object())  # type: ignore[arg-type]


def test_builder_rejects_duplicate_component() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    component = SecurityAuditComponentHealth(
        name="audit_logger",
        status=SecurityAuditComponentStatus.HEALTHY,
    )

    builder.add_component(component)

    with pytest.raises(ValueError):
        builder.add_component(component)


def test_builder_accepts_healthy_audit_report(
    healthy_report: AuditHealthReport,
) -> None:
    builder = SecurityAuditHealthStatusBuilder()

    builder.add_audit_health_report(healthy_report)

    result = builder.build()

    component = result.get_component("audit_logger")

    assert component is not None
    assert component.status is SecurityAuditComponentStatus.HEALTHY


def test_builder_accepts_unhealthy_audit_report(
    unhealthy_report: AuditHealthReport,
) -> None:
    builder = SecurityAuditHealthStatusBuilder()

    builder.add_audit_health_report(unhealthy_report)

    result = builder.build()

    component = result.get_component("audit_logger")

    assert component is not None
    assert component.status is SecurityAuditComponentStatus.UNHEALTHY


def test_builder_rejects_invalid_audit_report() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    with pytest.raises(TypeError):
        builder.add_audit_health_report(
            object()  # type: ignore[arg-type]
        )


def test_builder_adds_installed_api_component() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    builder.add_api_component(
        installed=True,
        prefix="/configuration/security/audit",
    )

    result = builder.build()

    component = result.get_component("health_api")

    assert component is not None
    assert component.status is SecurityAuditComponentStatus.HEALTHY
    assert component.details["installed"] is True
    assert (
        component.details["prefix"]
        == "/configuration/security/audit"
    )


def test_builder_adds_uninstalled_api_component() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    builder.add_api_component(installed=False)

    result = builder.build()

    component = result.get_component("health_api")

    assert component is not None
    assert (
        component.status
        is SecurityAuditComponentStatus.NOT_INSTALLED
    )


def test_builder_rejects_non_boolean_api_status() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    with pytest.raises(TypeError):
        builder.add_api_component(
            installed=1,  # type: ignore[arg-type]
        )


def test_builder_rejects_invalid_api_prefix() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    with pytest.raises(TypeError):
        builder.add_api_component(
            installed=True,
            prefix=123,  # type: ignore[arg-type]
        )


def test_builder_aggregates_all_healthy_components() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    builder.add_component(
        SecurityAuditComponentHealth(
            name="audit_logger",
            status=SecurityAuditComponentStatus.HEALTHY,
        )
    )
    builder.add_component(
        SecurityAuditComponentHealth(
            name="health_api",
            status=SecurityAuditComponentStatus.HEALTHY,
        )
    )

    result = builder.build()

    assert result.status is SecurityAuditSubsystemStatus.HEALTHY
    assert result.healthy is True


@pytest.mark.parametrize(
    ("component_status", "expected_status"),
    [
        (
            SecurityAuditComponentStatus.DEGRADED,
            SecurityAuditSubsystemStatus.DEGRADED,
        ),
        (
            SecurityAuditComponentStatus.NOT_INSTALLED,
            SecurityAuditSubsystemStatus.DEGRADED,
        ),
        (
            SecurityAuditComponentStatus.UNKNOWN,
            SecurityAuditSubsystemStatus.UNKNOWN,
        ),
        (
            SecurityAuditComponentStatus.UNHEALTHY,
            SecurityAuditSubsystemStatus.UNHEALTHY,
        ),
    ],
)
def test_builder_maps_component_status(
    component_status: SecurityAuditComponentStatus,
    expected_status: SecurityAuditSubsystemStatus,
) -> None:
    builder = SecurityAuditHealthStatusBuilder()

    builder.add_component(
        SecurityAuditComponentHealth(
            name="component",
            status=component_status,
            message="Component status",
        )
    )

    result = builder.build()

    assert result.status is expected_status


def test_unhealthy_component_has_highest_priority() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    builder.add_component(
        SecurityAuditComponentHealth(
            name="unknown_component",
            status=SecurityAuditComponentStatus.UNKNOWN,
        )
    )
    builder.add_component(
        SecurityAuditComponentHealth(
            name="degraded_component",
            status=SecurityAuditComponentStatus.DEGRADED,
        )
    )
    builder.add_component(
        SecurityAuditComponentHealth(
            name="unhealthy_component",
            status=SecurityAuditComponentStatus.UNHEALTHY,
        )
    )

    result = builder.build()

    assert result.status is SecurityAuditSubsystemStatus.UNHEALTHY


def test_builder_uses_supplied_timestamp() -> None:
    timestamp = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)

    builder = SecurityAuditHealthStatusBuilder()
    builder.add_component(
        SecurityAuditComponentHealth(
            name="audit_logger",
            status=SecurityAuditComponentStatus.HEALTHY,
        )
    )

    result = builder.build(checked_at=timestamp)

    assert result.checked_at == timestamp


def test_builder_rejects_naive_timestamp() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    with pytest.raises(ValueError):
        builder.build(
            checked_at=datetime(2026, 11, 13, 10, 0)
        )


def test_builder_rejects_non_datetime_timestamp() -> None:
    builder = SecurityAuditHealthStatusBuilder()

    with pytest.raises(TypeError):
        builder.build(
            checked_at="2026-11-13"  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def test_convenience_function_builds_healthy_status(
    healthy_report: AuditHealthReport,
) -> None:
    result = build_security_audit_health_status(
        audit_report=healthy_report,
        api_installed=True,
        api_prefix="/configuration/security/audit",
    )

    assert result.status is SecurityAuditSubsystemStatus.HEALTHY
    assert result.healthy is True


def test_convenience_function_reports_uninstalled_api(
    healthy_report: AuditHealthReport,
) -> None:
    result = build_security_audit_health_status(
        audit_report=healthy_report,
        api_installed=False,
    )

    assert result.status is SecurityAuditSubsystemStatus.DEGRADED


def test_convenience_function_reports_unavailable_audit_report() -> None:
    result = build_security_audit_health_status(
        audit_report=None,
        api_installed=True,
    )

    assert result.status is SecurityAuditSubsystemStatus.UNKNOWN

    component = result.get_component("audit_logger")

    assert component is not None
    assert component.status is SecurityAuditComponentStatus.UNKNOWN


def test_convenience_function_reports_unhealthy_audit_logger(
    unhealthy_report: AuditHealthReport,
) -> None:
    result = build_security_audit_health_status(
        audit_report=unhealthy_report,
        api_installed=True,
    )

    assert result.status is SecurityAuditSubsystemStatus.UNHEALTHY


def test_convenience_function_rejects_invalid_report() -> None:
    with pytest.raises(TypeError):
        build_security_audit_health_status(
            audit_report=object(),  # type: ignore[arg-type]
            api_installed=True,
        )


def test_convenience_function_rejects_invalid_api_status(
    healthy_report: AuditHealthReport,
) -> None:
    with pytest.raises(TypeError):
        build_security_audit_health_status(
            audit_report=healthy_report,
            api_installed=1,  # type: ignore[arg-type]
        )


def test_convenience_function_preserves_timestamp(
    healthy_report: AuditHealthReport,
) -> None:
    timestamp = datetime(
        2026, 11, 13, 12, 0, tzinfo=timezone.utc
    )

    result = build_security_audit_health_status(
        audit_report=healthy_report,
        api_installed=True,
        checked_at=timestamp,
    )

    assert result.checked_at == timestamp
