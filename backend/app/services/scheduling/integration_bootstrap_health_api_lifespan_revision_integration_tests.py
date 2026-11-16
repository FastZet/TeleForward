
"""Integration tests for the cancellation-aware bootstrap health lifespan."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

import app.services.scheduling.integration_bootstrap_health_api_lifespan_revision_integration as integration_module
from app.services.scheduling.integration_bootstrap_health_api_lifespan_revision_integration import (
    BootstrapHealthLifespanShutdownError,
    create_integrated_bootstrap_health_lifespan,
)


class FakeIntegration:
    """Minimal integration object for lifespan tests."""


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def install_fake_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace integration installation with a deterministic test double."""

    monkeypatch.setattr(
        integration_module,
        "SchedulingBootstrapHealthAPIIntegration",
        FakeIntegration,
    )

    async def install(
        _app: FastAPI,
        service=None,
    ) -> FakeIntegration:
        return FakeIntegration()

    monkeypatch.setattr(
        integration_module,
        "_install_integration",
        install,
    )


@pytest.mark.asyncio
async def test_successful_lifespan_runs_callbacks_in_order(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    events: list[str] = []

    async def before_start(_app: FastAPI) -> None:
        events.append("before_start")

    async def after_start(_app: FastAPI) -> None:
        events.append("after_start")

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_start=before_start,
        after_start=after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    async with lifespan(app):
        events.append("application")

    assert events == [
        "before_start",
        "after_start",
        "application",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_existing_lifespan_is_entered_before_startup_callbacks(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        events.append("existing_enter")
        try:
            yield
        finally:
            events.append("existing_exit")

    async def before_start(_app: FastAPI) -> None:
        events.append("before_start")

    async def after_start(_app: FastAPI) -> None:
        events.append("after_start")

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
        before_start=before_start,
        after_start=after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    async with lifespan(app):
        events.append("application")

    assert events == [
        "existing_enter",
        "before_start",
        "after_start",
        "application",
        "before_shutdown",
        "after_shutdown",
        "existing_exit",
    ]


@pytest.mark.asyncio
async def test_existing_lifespan_exit_runs_after_shutdown_callbacks(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        finally:
            events.append("existing_exit")

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    async with lifespan(app):
        pass

    assert events == [
        "before_shutdown",
        "after_shutdown",
        "existing_exit",
    ]


@pytest.mark.asyncio
async def test_application_exception_is_preserved(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    async def failing_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("shutdown failed")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=failing_shutdown,
    )

    with pytest.raises(
        ValueError,
        match="application failure",
    ):
        async with lifespan(app):
            raise ValueError("application failure")


@pytest.mark.asyncio
async def test_startup_exception_is_preserved_when_existing_lifespan_exists(
    app: FastAPI,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        finally:
            events.append("existing_exit")

    async def failing_before_start(_app: FastAPI) -> None:
        raise RuntimeError("startup failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
        before_start=failing_before_start,
    )

    with pytest.raises(RuntimeError, match="startup failure"):
        async with lifespan(app):
            pass

    assert events == ["existing_exit"]


@pytest.mark.asyncio
async def test_startup_exception_without_cleanup_operations_is_not_suppressed(
    app: FastAPI,
) -> None:
    """Regression test for return-in-finally exception suppression."""

    async def failing_before_start(_app: FastAPI) -> None:
        raise RuntimeError("startup failure without cleanup")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_start=failing_before_start,
    )

    with pytest.raises(
        RuntimeError,
        match="startup failure without cleanup",
    ):
        async with lifespan(app):
            pass


@pytest.mark.asyncio
async def test_shutdown_callbacks_continue_after_first_failure(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    events: list[str] = []

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")
        raise RuntimeError("first shutdown failure")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    with pytest.raises(BootstrapHealthLifespanShutdownError):
        async with lifespan(app):
            events.append("application")

    assert events == [
        "application",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_multiple_shutdown_failures_are_retained(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    async def before_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("first failure")

    async def after_shutdown(_app: FastAPI) -> None:
        raise ValueError("second failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    with pytest.raises(BootstrapHealthLifespanShutdownError) as captured:
        async with lifespan(app):
            pass

    report = captured.value.report

    assert len(report.failures) == 2
    assert report.failures[0].operation == "before_shutdown"
    assert report.failures[1].operation == "after_shutdown"


@pytest.mark.asyncio
async def test_existing_lifespan_exit_failure_is_retained(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        yield
        raise RuntimeError("existing exit failed")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
    )

    with pytest.raises(BootstrapHealthLifespanShutdownError) as captured:
        async with lifespan(app):
            pass

    assert len(captured.value.report.failures) == 1
    assert (
        captured.value.report.failures[0].operation
        == "existing_lifespan_exit"
    )


@pytest.mark.asyncio
async def test_repeated_external_cancellation_does_not_interrupt_cleanup(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleanup_completed = asyncio.Event()

    async def before_shutdown(_app: FastAPI) -> None:
        cleanup_started.set()
        await allow_cleanup.wait()
        cleanup_completed.set()

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=before_shutdown,
    )

    async def run() -> None:
        async with lifespan(app):
            await asyncio.Event().wait()

    task = asyncio.create_task(run())

    await asyncio.sleep(0)
    task.cancel()

    await asyncio.wait_for(cleanup_started.wait(), timeout=2)

    task.cancel()
    await asyncio.sleep(0)

    allow_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleanup_completed.is_set()


@pytest.mark.asyncio
async def test_cancellation_and_shutdown_failure_preserve_cancellation(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    async def failing_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("shutdown failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=failing_shutdown,
    )

    async def run() -> None:
        async with lifespan(app):
            await asyncio.Event().wait()

    task = asyncio.create_task(run())

    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError) as captured:
        await task

    assert isinstance(
        captured.value,
        asyncio.CancelledError,
    )


@pytest.mark.asyncio
async def test_existing_lifespan_receives_application_exception(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    received: list[type[BaseException] | None] = []

    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        except BaseException as exc:
            received.append(type(exc))
            raise

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
    )

    with pytest.raises(ValueError, match="application failure"):
        async with lifespan(app):
            raise ValueError("application failure")

    assert received == [ValueError]


@pytest.mark.asyncio
async def test_async_existing_lifespan_factory_is_supported(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def context(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        events.append("entered")
        try:
            yield
        finally:
            events.append("exited")

    async def factory(_app: FastAPI):
        events.append("factory")
        return context(_app)

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=factory,
    )

    async with lifespan(app):
        events.append("application")

    assert events == [
        "factory",
        "entered",
        "application",
        "exited",
    ]


@pytest.mark.asyncio
async def test_invalid_existing_lifespan_context_is_rejected(
    app: FastAPI,
) -> None:
    def invalid_factory(_app: FastAPI):
        return object()

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=invalid_factory,
    )

    with pytest.raises(
        TypeError,
        match="async context manager",
    ):
        async with lifespan(app):
            pass


def test_non_fastapi_application_is_rejected() -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    async def run() -> None:
        async with lifespan(object()):
            pass

    with pytest.raises(TypeError, match="FastAPI"):
        asyncio.run(run())


def test_non_callable_callback_is_rejected() -> None:
    with pytest.raises(TypeError, match="callbacks"):
        create_integrated_bootstrap_health_lifespan(
            before_start="not callable",
        )


def test_non_callable_existing_lifespan_is_rejected() -> None:
    with pytest.raises(TypeError, match="existing_lifespan"):
        create_integrated_bootstrap_health_lifespan(
            existing_lifespan="not callable",
        )
