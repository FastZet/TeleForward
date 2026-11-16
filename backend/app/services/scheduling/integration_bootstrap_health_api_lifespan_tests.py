
"""Tests for the bootstrap health API lifespan integration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI

from app.services.scheduling.integration_bootstrap_health import (
    SchedulingBootstrapHealthService,
)
from app.services.scheduling.integration_bootstrap_health_api import (
    BOOTSTRAP_HEALTH_API_PATH,
)
from app.services.scheduling.integration_bootstrap_health_api_integration import (
    get_bootstrap_health_api_integration_optional,
    is_bootstrap_health_api_integration_installed,
)
from app.services.scheduling.integration_bootstrap_health_api_lifespan import (
    BootstrapHealthLifespanError,
    create_bootstrap_health_api_lifespan,
    install_bootstrap_health_api_lifespan,
)


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def service() -> SchedulingBootstrapHealthService:
    return SchedulingBootstrapHealthService()


async def enter_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Enter the currently configured application lifespan."""
    async with app.router.lifespan_context(app):
        yield


@pytest.mark.asyncio
async def test_lifespan_installs_health_integration(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
    )

    async with lifespan(app):
        registration = get_bootstrap_health_api_integration_optional(
            app
        )

        assert registration is not None
        assert registration.service is service
        assert is_bootstrap_health_api_integration_installed(app)


@pytest.mark.asyncio
async def test_lifespan_registers_health_route(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
    )

    async with lifespan(app):
        paths = {
            route.path
            for route in app.routes
            if hasattr(route, "path")
        }

        assert BOOTSTRAP_HEALTH_API_PATH in paths


@pytest.mark.asyncio
async def test_startup_callback_order(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    async def before_start(_app: FastAPI) -> None:
        events.append("before_start")

    async def after_start(_app: FastAPI) -> None:
        events.append("after_start")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_start=before_start,
        after_start=after_start,
    )

    async with lifespan(app):
        events.append("application")

    assert events == [
        "before_start",
        "after_start",
        "application",
    ]


@pytest.mark.asyncio
async def test_shutdown_callback_order(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    async with lifespan(app):
        events.append("application")

    assert events == [
        "application",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_sync_callbacks_are_supported(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    def before_start(_app: FastAPI) -> None:
        events.append("before_start")

    def after_start(_app: FastAPI) -> None:
        events.append("after_start")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_start=before_start,
        after_start=after_start,
    )

    async with lifespan(app):
        pass

    assert events == ["before_start", "after_start"]


@pytest.mark.asyncio
async def test_existing_lifespan_is_preserved(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        events.append("existing_start")
        try:
            yield
        finally:
            events.append("existing_shutdown")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=existing_lifespan,
    )

    async with lifespan(app):
        events.append("application")

    assert events == [
        "existing_start",
        "application",
        "existing_shutdown",
    ]


@pytest.mark.asyncio
async def test_existing_lifespan_wraps_health_startup(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        events.append("existing_start")
        yield
        events.append("existing_shutdown")

    async def before_start(_app: FastAPI) -> None:
        events.append("health_before_start")

    async def after_start(_app: FastAPI) -> None:
        events.append("health_after_start")

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("health_before_shutdown")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("health_after_shutdown")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=existing_lifespan,
        before_start=before_start,
        after_start=after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    async with lifespan(app):
        events.append("application")

    assert events == [
        "existing_start",
        "health_before_start",
        "health_after_start",
        "application",
        "health_before_shutdown",
        "health_after_shutdown",
        "existing_shutdown",
    ]


@pytest.mark.asyncio
async def test_existing_lifespan_receives_application_exception(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    received_exceptions: list[type[BaseException] | None] = []

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        except BaseException as exc:
            received_exceptions.append(type(exc))
            raise

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=existing_lifespan,
    )

    with pytest.raises(ValueError, match="application failure"):
        async with lifespan(app):
            raise ValueError("application failure")

    assert received_exceptions == [ValueError]


@pytest.mark.asyncio
async def test_existing_lifespan_is_exited_when_startup_callback_fails(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        events.append("entered")
        try:
            yield
        finally:
            events.append("exited")

    async def failing_after_start(_app: FastAPI) -> None:
        raise RuntimeError("startup callback failure")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=existing_lifespan,
        after_start=failing_after_start,
    )

    with pytest.raises(RuntimeError, match="startup callback failure"):
        async with lifespan(app):
            pass

    assert events == ["entered", "exited"]


@pytest.mark.asyncio
async def test_existing_lifespan_is_not_entered_when_factory_fails(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    def invalid_lifespan(
        _app: FastAPI,
    ) -> Any:
        events.append("factory_called")
        return object()

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        existing_lifespan=invalid_lifespan,
    )

    with pytest.raises(BootstrapHealthLifespanError):
        async with lifespan(app):
            pass

    assert events == ["factory_called"]


@pytest.mark.asyncio
async def test_shutdown_callbacks_both_run_when_first_fails(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")
        raise RuntimeError("before shutdown failure")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    with pytest.raises(BootstrapHealthLifespanError):
        async with lifespan(app):
            events.append("application")

    assert events == [
        "application",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_shutdown_failure_does_not_replace_application_error(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    async def failing_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("shutdown failure")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_shutdown=failing_shutdown,
    )

    with pytest.raises(ValueError, match="application failure"):
        async with lifespan(app):
            raise ValueError("application failure")


@pytest.mark.asyncio
async def test_after_start_failure_leaves_registration_available(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    async def failing_after_start(_app: FastAPI) -> None:
        raise RuntimeError("after start failure")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        after_start=failing_after_start,
    )

    with pytest.raises(RuntimeError, match="after start failure"):
        async with lifespan(app):
            pass

    registration = get_bootstrap_health_api_integration_optional(
        app
    )

    assert registration is not None
    assert registration.service is service


@pytest.mark.asyncio
async def test_repeated_lifespan_execution_reuses_registration(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
    )

    async with lifespan(app):
        first = get_bootstrap_health_api_integration_optional(app)

    async with lifespan(app):
        second = get_bootstrap_health_api_integration_optional(app)

    assert first is not None
    assert second is first

    matching_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == BOOTSTRAP_HEALTH_API_PATH
    ]

    assert len(matching_routes) == 1


@pytest.mark.asyncio
async def test_repeated_lifespan_execution_with_no_explicit_service(
    app: FastAPI,
) -> None:
    lifespan = create_bootstrap_health_api_lifespan()

    async with lifespan(app):
        first = get_bootstrap_health_api_integration_optional(app)

    async with lifespan(app):
        second = get_bootstrap_health_api_integration_optional(app)

    assert first is not None
    assert second is first


@pytest.mark.asyncio
async def test_install_helper_wraps_existing_application_lifespan(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    original_lifespan = app.router.lifespan_context

    registered_lifespan = install_bootstrap_health_api_lifespan(
        app,
        service=service,
    )

    assert app.router.lifespan_context is registered_lifespan
    assert registered_lifespan is not original_lifespan

    async with app.router.lifespan_context(app):
        assert get_bootstrap_health_api_integration_optional(
            app
        ) is not None


def test_install_helper_rejects_invalid_app() -> None:
    with pytest.raises(TypeError):
        install_bootstrap_health_api_lifespan(
            object(),  # type: ignore[arg-type]
        )


def test_factory_rejects_service_and_bootstrap_together(
    service: SchedulingBootstrapHealthService,
) -> None:
    from app.services.scheduling.integration_bootstrap import (
        SchedulingIntegrationBootstrap,
    )

    with pytest.raises(ValueError):
        create_bootstrap_health_api_lifespan(
            service=service,
            bootstrap=SchedulingIntegrationBootstrap({}),
        )


def test_factory_rejects_non_callable_callback() -> None:
    with pytest.raises(TypeError):
        create_bootstrap_health_api_lifespan(
            before_start=object(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_cancellation_runs_shutdown_callbacks(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    with pytest.raises(asyncio.CancelledError):
        async with lifespan(app):
            raise asyncio.CancelledError()

    assert events == ["before_shutdown", "after_shutdown"]


@pytest.mark.asyncio
async def test_cancellation_during_startup_runs_shutdown_callbacks(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    events: list[str] = []

    async def failing_after_start(_app: FastAPI) -> None:
        raise asyncio.CancelledError()

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
        after_start=failing_after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    with pytest.raises(asyncio.CancelledError):
        async with lifespan(app):
            pass

    assert events == ["before_shutdown", "after_shutdown"]


@pytest.mark.asyncio
async def test_health_service_is_not_closed_on_lifespan_shutdown(
    app: FastAPI,
    service: SchedulingBootstrapHealthService,
) -> None:
    lifespan = create_bootstrap_health_api_lifespan(
        service=service,
    )

    async with lifespan(app):
        pass

    registration = get_bootstrap_health_api_integration_optional(
        app
    )

    assert registration is not None
    assert registration.service is service
