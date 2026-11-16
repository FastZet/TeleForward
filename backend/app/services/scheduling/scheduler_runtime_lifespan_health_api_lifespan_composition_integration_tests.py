
"""Tests for scheduler health API lifespan composition integration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from app.services.scheduling import (
    scheduler_runtime_lifespan_health_api_lifespan_composition_integration
    as integration,
)


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application."""

    return FastAPI()


def make_lifespan(events: list[str], name: str):
    """Create a lifespan factory that records lifecycle events."""

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        events.append(f"{name}_startup")
        try:
            yield
        finally:
            events.append(f"{name}_shutdown")

    return lifespan


def test_install_registers_composed_lifespan(
    app: FastAPI,
) -> None:
    """Installation must register a callable composed lifespan."""

    lifespan = (
        integration.install_scheduler_health_api_lifespan_composition(
            app
        )
    )

    assert callable(lifespan)

    assert integration.is_scheduler_health_api_lifespan_composed(
        app
    )

    assert (
        integration.get_scheduler_health_api_lifespan_composition(
            app
        )
        is lifespan
    )


def test_install_records_supplied_lifespan_factories(
    app: FastAPI,
) -> None:
    """Installation must record which factories were supplied."""

    events: list[str] = []

    existing = make_lifespan(events, "application")
    scheduler = make_lifespan(events, "scheduler")
    health = make_lifespan(events, "health")

    integration.install_scheduler_health_api_lifespan_composition(
        app,
        existing_lifespan=existing,
        scheduler_runtime_lifespan=scheduler,
        health_api_lifespan=health,
    )

    state = (
        integration.get_scheduler_health_api_lifespan_composition_status(
            app
        )
    )

    assert state == {
        "installed": True,
        "lifespan_valid": True,
        "consistent": True,
        "existing_lifespan_supplied": True,
        "scheduler_runtime_lifespan_supplied": True,
        "health_api_lifespan_supplied": True,
    }


def test_install_records_partial_configuration(
    app: FastAPI,
) -> None:
    """Optional factories must be reflected accurately."""

    events: list[str] = []

    scheduler = make_lifespan(events, "scheduler")

    integration.install_scheduler_health_api_lifespan_composition(
        app,
        scheduler_runtime_lifespan=scheduler,
    )

    state = (
        integration.get_scheduler_health_api_lifespan_composition_status(
            app
        )
    )

    assert state["existing_lifespan_supplied"] is False
    assert state["scheduler_runtime_lifespan_supplied"] is True
    assert state["health_api_lifespan_supplied"] is False


def test_composed_lifespan_executes_all_contexts(
    app: FastAPI,
) -> None:
    """The registered composition must preserve lifecycle ordering."""

    events: list[str] = []

    lifespan = (
        integration.install_scheduler_health_api_lifespan_composition(
            app,
            existing_lifespan=make_lifespan(
                events,
                "application",
            ),
            scheduler_runtime_lifespan=make_lifespan(
                events,
                "scheduler",
            ),
            health_api_lifespan=make_lifespan(
                events,
                "health",
            ),
        )
    )

    async def run_lifespan() -> None:
        async with lifespan(app):
            events.append("running")

    import asyncio

    asyncio.run(run_lifespan())

    assert events == [
        "application_startup",
        "scheduler_startup",
        "health_startup",
        "running",
        "health_shutdown",
        "scheduler_shutdown",
        "application_shutdown",
    ]


def test_get_returns_exact_registered_factory(
    app: FastAPI,
) -> None:
    """Retrieval must return the original composition factory."""

    installed = (
        integration.install_scheduler_health_api_lifespan_composition(
            app
        )
    )

    retrieved = (
        integration.get_scheduler_health_api_lifespan_composition(
            app
        )
    )

    assert retrieved is installed


def test_get_rejects_missing_composition(
    app: FastAPI,
) -> None:
    """Retrieval must fail when no composition is registered."""

    with pytest.raises(
        integration.SchedulerHealthAPILifespanCompositionIntegrationError,
        match="not installed",
    ):
        integration.get_scheduler_health_api_lifespan_composition(
            app
        )


def test_duplicate_installation_is_rejected(
    app: FastAPI,
) -> None:
    """Repeated installation must be rejected."""

    integration.install_scheduler_health_api_lifespan_composition(
        app
    )

    with pytest.raises(
        integration.SchedulerHealthAPILifespanCompositionIntegrationError,
        match="already installed",
    ):
        integration.install_scheduler_health_api_lifespan_composition(
            app
        )


def test_status_reports_uninstalled_state(
    app: FastAPI,
) -> None:
    """An untouched application must report an uninstalled state."""

    state = (
        integration.get_scheduler_health_api_lifespan_composition_status(
            app
        )
    )

    assert state == {
        "installed": False,
        "lifespan_valid": False,
        "consistent": True,
        "existing_lifespan_supplied": False,
        "scheduler_runtime_lifespan_supplied": False,
        "health_api_lifespan_supplied": False,
    }


def test_status_reports_installed_state(
    app: FastAPI,
) -> None:
    """A valid composition must be reported as consistent."""

    integration.install_scheduler_health_api_lifespan_composition(
        app
    )

    state = (
        integration.get_scheduler_health_api_lifespan_composition_status(
            app
        )
    )

    assert state["installed"] is True
    assert state["lifespan_valid"] is True
    assert state["consistent"] is True


def test_status_detects_non_callable_lifespan(
    app: FastAPI,
) -> None:
    """A corrupted lifespan factory must be reported as invalid."""

    integration.install_scheduler_health_api_lifespan_composition(
        app
    )

    state = getattr(
        app.state,
        integration.COMPOSITION_STATE_KEY,
    )

    state["lifespan"] = "invalid"

    result = (
        integration.get_scheduler_health_api_lifespan_composition_status(
            app
        )
    )

    assert result["installed"] is True
    assert result["lifespan_valid"] is False
    assert result["consistent"] is False


def test_get_rejects_non_callable_lifespan(
    app: FastAPI,
) -> None:
    """Retrieval must reject corrupted lifespan metadata."""

    integration.install_scheduler_health_api_lifespan_composition(
        app
    )

    state = getattr(
        app.state,
        integration.COMPOSITION_STATE_KEY,
    )

    state["lifespan"] = "invalid"

    with pytest.raises(
        integration.SchedulerHealthAPILifespanCompositionIntegrationError,
        match="composition is invalid",
    ):
        integration.get_scheduler_health_api_lifespan_composition(
            app
        )


def test_status_rejects_malformed_state(
    app: FastAPI,
) -> None:
    """Malformed app.state metadata must be rejected."""

    setattr(
        app.state,
        integration.COMPOSITION_STATE_KEY,
        "invalid",
    )

    with pytest.raises(
        integration.SchedulerHealthAPILifespanCompositionIntegrationError,
        match="state is invalid",
    ):
        integration.get_scheduler_health_api_lifespan_composition_status(
            app
        )


def test_is_composed_returns_false_before_installation(
    app: FastAPI,
) -> None:
    """An application without a composition must return false."""

    assert not integration.is_scheduler_health_api_lifespan_composed(
        app
    )


def test_is_composed_returns_false_for_invalid_factory(
    app: FastAPI,
) -> None:
    """A registered non-callable factory must not count as composed."""

    setattr(
        app.state,
        integration.COMPOSITION_STATE_KEY,
        {
            "installed": True,
            "lifespan": "invalid",
        },
    )

    assert not integration.is_scheduler_health_api_lifespan_composed(
        app
    )


def test_remove_clears_composition_metadata(
    app: FastAPI,
) -> None:
    """Removal must clear composition registration metadata."""

    integration.install_scheduler_health_api_lifespan_composition(
        app
    )

    integration.remove_scheduler_health_api_lifespan_composition(
        app
    )

    assert getattr(
        app.state,
        integration.COMPOSITION_STATE_KEY,
        None,
    ) is None

    assert not integration.is_scheduler_health_api_lifespan_composed(
        app
    )


def test_remove_is_safe_when_not_installed(
    app: FastAPI,
) -> None:
    """Removing absent metadata must be harmless."""

    integration.remove_scheduler_health_api_lifespan_composition(
        app
    )

    assert not integration.is_scheduler_health_api_lifespan_composed(
        app
    )


def test_remove_does_not_modify_active_lifespan_reference(
    app: FastAPI,
) -> None:
    """Removing metadata must not claim to change FastAPI's lifespan."""

    lifespan = (
        integration.install_scheduler_health_api_lifespan_composition(
            app
        )
    )

    app.router.lifespan_context = lifespan

    integration.remove_scheduler_health_api_lifespan_composition(
        app
    )

    assert app.router.lifespan_context is lifespan


def test_install_rejects_invalid_application() -> None:
    """Installation must require a FastAPI instance."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.install_scheduler_health_api_lifespan_composition(
            Mock()
        )


def test_get_rejects_invalid_application() -> None:
    """Retrieval must require a FastAPI instance."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.get_scheduler_health_api_lifespan_composition(
            Mock()
        )


def test_status_rejects_invalid_application() -> None:
    """Status inspection must require a FastAPI instance."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.get_scheduler_health_api_lifespan_composition_status(
            Mock()
        )


def test_remove_rejects_invalid_application() -> None:
    """Removal must require a FastAPI instance."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.remove_scheduler_health_api_lifespan_composition(
            Mock()
        )


def test_is_composed_rejects_invalid_application() -> None:
    """Composition inspection must require a FastAPI instance."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        integration.is_scheduler_health_api_lifespan_composed(
            Mock()
        )


def test_install_rejects_invalid_existing_lifespan(
    app: FastAPI,
) -> None:
    """An invalid existing lifespan factory must be rejected."""

    with pytest.raises(
        TypeError,
        match="existing_lifespan must be callable",
    ):
        integration.install_scheduler_health_api_lifespan_composition(
            app,
            existing_lifespan="invalid",  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_scheduler_lifespan(
    app: FastAPI,
) -> None:
    """An invalid scheduler lifespan factory must be rejected."""

    with pytest.raises(
        TypeError,
        match="scheduler_runtime_lifespan must be callable",
    ):
        integration.install_scheduler_health_api_lifespan_composition(
            app,
            scheduler_runtime_lifespan=123,  # type: ignore[arg-type]
        )


def test_install_rejects_invalid_health_lifespan(
    app: FastAPI,
) -> None:
    """An invalid health lifespan factory must be rejected."""

    with pytest.raises(
        TypeError,
        match="health_api_lifespan must be callable",
    ):
        integration.install_scheduler_health_api_lifespan_composition(
            app,
            health_api_lifespan=False,  # type: ignore[arg-type]
        )
