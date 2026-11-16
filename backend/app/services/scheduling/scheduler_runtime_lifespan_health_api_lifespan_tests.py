
"""Tests for scheduler health API lifespan integration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.scheduling import (
    scheduler_runtime_lifespan_health_api_lifespan as health_lifespan,
)
from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerRuntimeLifespanHealthService,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_api_integration import (
    INTEGRATION_STATE_KEY,
)


def apply_lifespan(
    app: FastAPI,
    lifespan,
) -> None:
    app.router.lifespan_context = lifespan


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI application."""

    return FastAPI()


@pytest.fixture
def service(
    app: FastAPI,
) -> SchedulerRuntimeLifespanHealthService:
    """Create a health service bound to the application."""

    return SchedulerRuntimeLifespanHealthService(app=app)


def test_create_lifespan_returns_callable() -> None:
    """The lifespan factory must return a callable."""

    lifespan = health_lifespan.create_scheduler_health_api_lifespan()

    assert callable(lifespan)


def test_lifespan_installs_health_api_on_startup(
    app: FastAPI,
) -> None:
    """Entering the lifespan must install the health API."""

    lifespan = health_lifespan.create_scheduler_health_api_lifespan()
    apply_lifespan(app, lifespan)

    with TestClient(app) as client:
        # Entering TestClient starts the FastAPI lifespan.
        assert health_lifespan.is_scheduler_health_api_lifespan_registered(
            app
        ) is False

        assert getattr(
            app.state,
            INTEGRATION_STATE_KEY,
            False,
        )

        assert "/health/scheduler" in {
            route.path
            for route in app.routes
        }

        # The route exists even when no scheduler runtime is installed.
        response = client.get("/health/scheduler")
        assert response.status_code == 503


def test_lifespan_uses_supplied_service(
    app: FastAPI,
    service: SchedulerRuntimeLifespanHealthService,
) -> None:
    """A supplied service must be installed during startup."""

    lifespan = health_lifespan.create_scheduler_health_api_lifespan(
        service=service,
    )
    apply_lifespan(app, lifespan)

    with TestClient(app):
        from app.services.scheduling.scheduler_runtime_lifespan_health_api_integration import (
            get_scheduler_health_api_integration,
        )

        assert (
            get_scheduler_health_api_integration(app)
            is service
        )


def test_existing_lifespan_startup_and_shutdown_are_preserved(
    app: FastAPI,
) -> None:
    """The existing lifespan must remain active around health setup."""

    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(application: FastAPI):
        events.append("existing_startup")
        yield
        events.append("existing_shutdown")

    lifespan = health_lifespan.create_scheduler_health_api_lifespan(
        existing_lifespan=existing_lifespan,
    )
    apply_lifespan(app, lifespan)

    with TestClient(app):
        events.append("application_running")

    assert events == [
        "existing_startup",
        "application_running",
        "existing_shutdown",
    ]


def test_existing_lifespan_cleanup_runs_after_health_startup_failure(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing lifespan cleanup must run when health setup fails."""

    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(application: FastAPI):
        events.append("existing_startup")
        try:
            yield
        finally:
            events.append("existing_shutdown")

    def fail_health_setup(
        application: FastAPI,
        service: SchedulerRuntimeLifespanHealthService | None,
    ) -> None:
        raise RuntimeError("Simulated health setup failure")

    monkeypatch.setattr(
        health_lifespan,
        "_ensure_health_api_installed",
        fail_health_setup,
    )

    lifespan = health_lifespan.create_scheduler_health_api_lifespan(
        existing_lifespan=existing_lifespan,
    )
    apply_lifespan(app, lifespan)

    with pytest.raises(
        RuntimeError,
        match="Simulated health setup failure",
    ):
        with TestClient(app):
            pass

    assert events == [
        "existing_startup",
        "existing_shutdown",
    ]


def test_existing_lifespan_startup_failure_is_wrapped(
    app: FastAPI,
) -> None:
    """An existing lifespan startup failure must be wrapped."""

    @asynccontextmanager
    async def existing_lifespan(application: FastAPI):
        raise RuntimeError("Existing startup failed")
        yield

    lifespan = health_lifespan.create_scheduler_health_api_lifespan(
        existing_lifespan=existing_lifespan,
    )
    apply_lifespan(app, lifespan)

    with pytest.raises(
        health_lifespan.SchedulerHealthAPILifespanError,
        match="Existing application lifespan failed to start",
    ):
        with TestClient(app):
            pass


def test_application_exception_propagates_through_lifespan(
    app: FastAPI,
) -> None:
    """Application exceptions must not be swallowed."""

    lifespan = health_lifespan.create_scheduler_health_api_lifespan()
    apply_lifespan(app, lifespan)

    with pytest.raises(
        RuntimeError,
        match="Application failure",
    ):
        with TestClient(app):
            raise RuntimeError("Application failure")


def test_health_integration_remains_installed_after_shutdown(
    app: FastAPI,
) -> None:
    """The integration must remain installed after lifespan exit."""

    lifespan = health_lifespan.create_scheduler_health_api_lifespan()
    apply_lifespan(app, lifespan)

    with TestClient(app):
        pass

    from app.services.scheduling.scheduler_runtime_lifespan_health_api_integration import (
        get_scheduler_health_api_integration,
    )

    assert isinstance(
        get_scheduler_health_api_integration(app),
        SchedulerRuntimeLifespanHealthService,
    )

    assert getattr(
        app.state,
        INTEGRATION_STATE_KEY,
        False,
    )


def test_install_lifespan_registers_factory(
    app: FastAPI,
) -> None:
    """The registration helper must store the lifespan factory."""

    lifespan = health_lifespan.install_scheduler_health_api_lifespan(
        app
    )

    assert (
        health_lifespan.get_scheduler_health_api_lifespan(app)
        is lifespan
    )

    assert health_lifespan.is_scheduler_health_api_lifespan_registered(
        app
    )


def test_get_lifespan_rejects_unregistered_application(
    app: FastAPI,
) -> None:
    """Getting an unregistered lifespan must raise an error."""

    with pytest.raises(
        health_lifespan.SchedulerHealthAPILifespanError,
        match="not registered",
    ):
        health_lifespan.get_scheduler_health_api_lifespan(
            app
        )


def test_install_lifespan_rejects_invalid_application() -> None:
    """Registration must require a FastAPI application."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        health_lifespan.install_scheduler_health_api_lifespan(
            Mock()
        )


def test_create_lifespan_rejects_invalid_existing_lifespan() -> None:
    """An invalid existing lifespan must be rejected."""

    with pytest.raises(
        TypeError,
        match="existing_lifespan must be callable",
    ):
        health_lifespan.create_scheduler_health_api_lifespan(
            existing_lifespan="invalid",  # type: ignore[arg-type]
        )


def test_create_lifespan_rejects_invalid_service(
) -> None:
    """An invalid health service must be rejected."""

    with pytest.raises(
        TypeError,
        match="SchedulerRuntimeLifespanHealthService",
    ):
        health_lifespan.create_scheduler_health_api_lifespan(
            service=Mock(),  # type: ignore[arg-type]
        )


def test_is_registered_returns_false_before_registration(
    app: FastAPI,
) -> None:
    """An application without a registered lifespan returns false."""

    assert not health_lifespan.is_scheduler_health_api_lifespan_registered(
        app
    )


def test_is_registered_rejects_invalid_application() -> None:
    """Registration inspection must require a FastAPI application."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        health_lifespan.is_scheduler_health_api_lifespan_registered(
            Mock()
        )


def test_get_lifespan_rejects_invalid_application() -> None:
    """Lifespan retrieval must require a FastAPI application."""

    with pytest.raises(
        TypeError,
        match="FastAPI instance",
    ):
        health_lifespan.get_scheduler_health_api_lifespan(
            Mock()
        )
