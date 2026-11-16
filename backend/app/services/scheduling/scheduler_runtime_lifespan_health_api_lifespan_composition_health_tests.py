
"""Tests for scheduler health API lifespan composition health."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan_composition_health import (
    CompositionHealthReport,
    CompositionHealthStatus,
    SchedulerHealthAPILifespanCompositionHealthService,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan_composition_integration import (
    COMPOSITION_STATE_KEY,
    install_scheduler_health_api_lifespan_composition,
)


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application."""

    return FastAPI()


@pytest.fixture
def service(
    app: FastAPI,
) -> SchedulerHealthAPILifespanCompositionHealthService:
    """Create a health inspection service."""

    return SchedulerHealthAPILifespanCompositionHealthService(
        app=app
    )


def install_complete_composition(
    app: FastAPI,
) -> None:
    """Install a complete composition and assign it to the router."""

    lifespan = install_scheduler_health_api_lifespan_composition(
        app,
        scheduler_runtime_lifespan=lambda application: None,
        health_api_lifespan=lambda application: None,
    )

    app.router.lifespan_context = lifespan


def test_constructor_accepts_optional_application() -> None:
    """The service can be constructed without an application."""

    service = SchedulerHealthAPILifespanCompositionHealthService()

    assert service.app is None


def test_constructor_binds_application(
    app: FastAPI,
) -> None:
    """The constructor must retain the supplied application."""

    service = SchedulerHealthAPILifespanCompositionHealthService(
        app=app
    )

    assert service.app is app


def test_constructor_rejects_invalid_application() -> None:
    """The constructor must reject non-FastAPI applications."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        SchedulerHealthAPILifespanCompositionHealthService(
            app=Mock()
        )


def test_bind_updates_application(
    app: FastAPI,
) -> None:
    """Binding must update the application reference."""

    service = SchedulerHealthAPILifespanCompositionHealthService()

    service.bind(app)

    assert service.app is app


def test_bind_rejects_invalid_application() -> None:
    """Binding must require a FastAPI application."""

    service = SchedulerHealthAPILifespanCompositionHealthService()

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        service.bind(Mock())


def test_inspect_requires_application() -> None:
    """Inspection must fail when no application is available."""

    service = SchedulerHealthAPILifespanCompositionHealthService()

    with pytest.raises(
        TypeError,
        match="must be supplied or bound",
    ):
        service.inspect()


def test_inspect_returns_unavailable_without_composition(
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """An unregistered composition must be unavailable."""

    report = service.inspect()

    assert report.status is CompositionHealthStatus.UNAVAILABLE
    assert report.installed is False
    assert report.lifespan_valid is False
    assert report.scheduler_lifespan_supplied is False
    assert report.health_api_lifespan_supplied is False
    assert report.application_lifespan_assigned is False
    assert not report.is_healthy
    assert "not registered" in report.details[0]


def test_inspect_returns_healthy_for_complete_composition(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """A complete assigned composition must be healthy."""

    install_complete_composition(app)

    report = service.inspect()

    assert report.status is CompositionHealthStatus.HEALTHY
    assert report.installed is True
    assert report.lifespan_valid is True
    assert report.scheduler_lifespan_supplied is True
    assert report.health_api_lifespan_supplied is True
    assert report.application_lifespan_assigned is True
    assert report.details == ()
    assert report.is_healthy


def test_inspect_returns_degraded_when_not_assigned(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """An unassigned composition must be degraded."""

    install_scheduler_health_api_lifespan_composition(
        app,
        scheduler_runtime_lifespan=lambda application: None,
        health_api_lifespan=lambda application: None,
    )

    report = service.inspect()

    assert report.status is CompositionHealthStatus.DEGRADED
    assert report.installed is True
    assert report.lifespan_valid is True
    assert report.application_lifespan_assigned is False
    assert any(
        "not assigned" in detail
        for detail in report.details
    )


def test_inspect_returns_degraded_without_scheduler_lifespan(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """A missing scheduler lifespan must produce degraded health."""

    install_scheduler_health_api_lifespan_composition(
        app,
        health_api_lifespan=lambda application: None,
    )

    lifespan = getattr(app.state, COMPOSITION_STATE_KEY, None)

    app.router.lifespan_context = lifespan["lifespan"]

    report = service.inspect()

    assert report.status is CompositionHealthStatus.DEGRADED
    assert report.scheduler_lifespan_supplied is False
    assert report.health_api_lifespan_supplied is True


def test_inspect_returns_degraded_without_health_api_lifespan(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """A missing health API lifespan must produce degraded health."""

    install_scheduler_health_api_lifespan_composition(
        app,
        scheduler_runtime_lifespan=lambda application: None,
    )

    state = getattr(app.state, COMPOSITION_STATE_KEY)
    app.router.lifespan_context = state["lifespan"]

    report = service.inspect()

    assert report.status is CompositionHealthStatus.DEGRADED
    assert report.scheduler_lifespan_supplied is True
    assert report.health_api_lifespan_supplied is False


def test_inspect_returns_failed_for_invalid_factory(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """An invalid registered factory must produce failed health."""

    install_complete_composition(app)

    state = getattr(app.state, COMPOSITION_STATE_KEY)
    state["lifespan"] = "invalid"

    report = service.inspect()

    assert report.status is CompositionHealthStatus.FAILED
    assert report.installed is True
    assert report.lifespan_valid is False
    assert not report.is_healthy


def test_inspect_returns_failed_for_malformed_state(
    app: FastAPI,
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """Malformed integration state must produce failed health."""

    setattr(app.state, COMPOSITION_STATE_KEY, "invalid")

    report = service.inspect()

    assert report.status is CompositionHealthStatus.FAILED
    assert report.installed is False
    assert report.lifespan_valid is False
    assert "Unable to inspect" in report.details[0]


def test_inspect_uses_application_override(
    app: FastAPI,
) -> None:
    """An explicit application must override the bound application."""

    other_app = FastAPI()

    install_complete_composition(other_app)

    service = SchedulerHealthAPILifespanCompositionHealthService(
        app=app
    )

    report = service.inspect(other_app)

    assert report.status is CompositionHealthStatus.HEALTHY
    assert service.app is app


def test_inspect_rejects_invalid_application_override(
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """An invalid application override must be rejected."""

    with pytest.raises(
        TypeError,
        match="must be supplied or bound",
    ):
        service.inspect(Mock())


def test_is_healthy_returns_true_for_healthy_composition(
    app: FastAPI,
) -> None:
    """is_healthy must return true for a healthy composition."""

    install_complete_composition(app)

    service = SchedulerHealthAPILifespanCompositionHealthService(
        app=app
    )

    assert service.is_healthy() is True


def test_is_healthy_returns_false_for_unavailable_composition(
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """is_healthy must return false when no composition exists."""

    assert service.is_healthy() is False


def test_get_status_returns_current_status(
    app: FastAPI,
) -> None:
    """get_status must expose the current health classification."""

    install_complete_composition(app)

    service = SchedulerHealthAPILifespanCompositionHealthService(
        app=app
    )

    assert service.get_status() is CompositionHealthStatus.HEALTHY


def test_report_contains_timezone_aware_timestamp(
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """Inspection timestamps must be timezone-aware."""

    report = service.inspect()

    assert report.checked_at.tzinfo is not None
    assert report.checked_at.utcoffset() is not None


def test_report_serializes_to_dictionary(
    service: SchedulerHealthAPILifespanCompositionHealthService,
) -> None:
    """The report must produce a JSON-compatible dictionary."""

    report = service.inspect()
    data = report.to_dict()

    assert data["status"] == "unavailable"
    assert data["is_healthy"] is False
    assert isinstance(data["checked_at"], str)
    assert isinstance(data["details"], list)


def test_report_is_frozen() -> None:
    """Report fields must not be reassigned."""

    report = CompositionHealthReport(
        status=CompositionHealthStatus.HEALTHY,
        installed=True,
        lifespan_valid=True,
        scheduler_lifespan_supplied=True,
        health_api_lifespan_supplied=True,
        application_lifespan_assigned=True,
        checked_at=datetime.now(UTC),
    )

    with pytest.raises(AttributeError):
        report.status = CompositionHealthStatus.FAILED  # type: ignore[misc]


def test_report_rejects_invalid_status() -> None:
    """The report must require a valid status enum."""

    with pytest.raises(
        TypeError,
        match="CompositionHealthStatus",
    ):
        CompositionHealthReport(
            status="healthy",  # type: ignore[arg-type]
            installed=True,
            lifespan_valid=True,
            scheduler_lifespan_supplied=True,
            health_api_lifespan_supplied=True,
            application_lifespan_assigned=True,
            checked_at=datetime.now(UTC),
        )


def test_report_rejects_non_boolean_state() -> None:
    """State fields must be actual booleans."""

    with pytest.raises(
        TypeError,
        match="must be booleans",
    ):
        CompositionHealthReport(
            status=CompositionHealthStatus.HEALTHY,
            installed=1,  # type: ignore[arg-type]
            lifespan_valid=True,
            scheduler_lifespan_supplied=True,
            health_api_lifespan_supplied=True,
            application_lifespan_assigned=True,
            checked_at=datetime.now(UTC),
        )


def test_report_rejects_naive_timestamp() -> None:
    """Naive timestamps must not be accepted."""

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        CompositionHealthReport(
            status=CompositionHealthStatus.HEALTHY,
            installed=True,
            lifespan_valid=True,
            scheduler_lifespan_supplied=True,
            health_api_lifespan_supplied=True,
            application_lifespan_assigned=True,
            checked_at=datetime.now(),
        )


def test_report_rejects_non_tuple_details() -> None:
    """Details must be supplied as an immutable tuple."""

    with pytest.raises(
        TypeError,
        match="details must be a tuple",
    ):
        CompositionHealthReport(
            status=CompositionHealthStatus.HEALTHY,
            installed=True,
            lifespan_valid=True,
            scheduler_lifespan_supplied=True,
            health_api_lifespan_supplied=True,
            application_lifespan_assigned=True,
            checked_at=datetime.now(UTC),
            details=["invalid"],  # type: ignore[arg-type]
        )


def test_report_rejects_non_string_detail() -> None:
    """Every detail entry must be a string."""

    with pytest.raises(
        TypeError,
        match="Every health detail",
    ):
        CompositionHealthReport(
            status=CompositionHealthStatus.HEALTHY,
            installed=True,
            lifespan_valid=True,
            scheduler_lifespan_supplied=True,
            health_api_lifespan_supplied=True,
            application_lifespan_assigned=True,
            checked_at=datetime.now(UTC),
            details=(123,),  # type: ignore[arg-type]
        )
