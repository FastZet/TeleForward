
"""Regression tests for the hardened bootstrap health API lifespan."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

import app.services.scheduling.integration_bootstrap_health_api_lifespan_revision_integration as integration_module
from app.services.scheduling.integration_bootstrap_health_api_lifespan_revision import (
    CleanupCancelledError,
)
from app.services.scheduling.integration_bootstrap_health_api_lifespan_revision_integration import (
    BootstrapHealthLifespanShutdownError,
    create_integrated_bootstrap_health_lifespan,
)


class FakeIntegration:
    """Minimal integration object for isolated lifespan tests."""


@pytest.fixture
def app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def install_fake_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replace health integration installation with a test double."""

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
async def test_successful_lifespan_callback_order(
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
async def test_existing_lifespan_entry_and_exit_order(
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
async def test_startup_failure_is_not_suppressed_without_existing_lifespan(
    app: FastAPI,
) -> None:
    async def failing_before_start(_app: FastAPI) -> None:
        raise RuntimeError("startup failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_start=failing_before_start,
    )

    with pytest.raises(RuntimeError, match="startup failure"):
        async with lifespan(app):
            pytest.fail("Application body must not execute")


@pytest.mark.asyncio
async def test_existing_lifespan_exits_after_startup_failure(
    app: FastAPI,
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

    async def failing_before_start(_app: FastAPI) -> None:
        raise RuntimeError("startup failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
        before_start=failing_before_start,
    )

    with pytest.raises(RuntimeError, match="startup failure"):
        async with lifespan(app):
            pass

    assert events == ["entered", "exited"]


@pytest.mark.asyncio
async def test_existing_lifespan_can_suppress_application_exception(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def suppressing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        except ValueError:
            events.append("suppressed")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=suppressing_lifespan,
    )

    async with lifespan(app):
        raise ValueError("ordinary application exception")

    assert events == ["suppressed"]


@pytest.mark.asyncio
async def test_existing_lifespan_can_suppress_startup_exception(
    app: FastAPI,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def suppressing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        except RuntimeError:
            events.append("startup_suppressed")

    async def failing_before_start(_app: FastAPI) -> None:
        raise RuntimeError("startup failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=suppressing_lifespan,
        before_start=failing_before_start,
    )

    async with lifespan(app):
        pytest.fail("Application body must not execute")

    assert events == ["startup_suppressed"]


@pytest.mark.asyncio
async def test_existing_lifespan_cannot_suppress_primary_cancellation(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def suppressing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        except asyncio.CancelledError:
            events.append("cancellation_suppressed")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=suppressing_lifespan,
    )

    with pytest.raises(asyncio.CancelledError):
        async with lifespan(app):
            raise asyncio.CancelledError("primary application cancellation")

    assert events == ["cancellation_suppressed"]


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_replace_primary_application_exception(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    async def failing_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("secondary shutdown failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=failing_shutdown,
    )

    with pytest.raises(ValueError, match="primary application failure") as captured:
        async with lifespan(app):
            raise ValueError("primary application failure")

    notes = getattr(captured.value, "__notes__", [])

    assert any(
        "Secondary lifespan cleanup diagnostics" in note
        for note in notes
    )
    assert any(
        "secondary shutdown failure" in note
        for note in notes
    )


@pytest.mark.asyncio
async def test_cleanup_cancellation_does_not_replace_primary_exception(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    async def cancelling_shutdown(_app: FastAPI) -> None:
        raise asyncio.CancelledError("secondary cleanup cancellation")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=cancelling_shutdown,
    )

    with pytest.raises(ValueError, match="primary failure") as captured:
        async with lifespan(app):
            raise ValueError("primary failure")

    notes = getattr(captured.value, "__notes__", [])

    assert any(
        "Cleanup cancellation" in note
        for note in notes
    )


@pytest.mark.asyncio
async def test_primary_cancellation_remains_primary_when_cleanup_fails(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    async def failing_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("cleanup failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=failing_shutdown,
    )

    with pytest.raises(asyncio.CancelledError) as captured:
        async with lifespan(app):
            raise asyncio.CancelledError("primary cancellation")

    notes = getattr(captured.value, "__notes__", [])

    assert any(
        "cleanup failure" in note
        for note in notes
    )


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

    failures = captured.value.report.failures

    assert len(failures) == 2
    assert failures[0].operation == "before_shutdown"
    assert failures[1].operation == "after_shutdown"


@pytest.mark.asyncio
async def test_cleanup_failure_is_reported_after_exception_suppression(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    @asynccontextmanager
    async def suppressing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            yield
        except ValueError:
            pass

    async def failing_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("shutdown failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=suppressing_lifespan,
        before_shutdown=failing_shutdown,
    )

    with pytest.raises(BootstrapHealthLifespanShutdownError):
        async with lifespan(app):
            raise ValueError("suppressed application exception")


@pytest.mark.asyncio
async def test_cleanup_cancellation_is_reported_separately(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    async def cancelling_shutdown(_app: FastAPI) -> None:
        raise asyncio.CancelledError()

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=cancelling_shutdown,
    )

    with pytest.raises(CleanupCancelledError) as captured:
        async with lifespan(app):
            pass

    assert captured.value.report.cancellation is not None
    assert captured.value.report.cancellation_count == 1


@pytest.mark.asyncio
async def test_external_cancellation_does_not_interrupt_cleanup(
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

    with pytest.raises(CleanupCancelledError) as captured:
        await task

    assert cleanup_completed.is_set()
    assert captured.value.report.cancellation_count >= 1


@pytest.mark.asyncio
async def test_existing_lifespan_exit_failure_is_retained(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    @asynccontextmanager
    async def failing_existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        yield
        raise RuntimeError("existing exit failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=failing_existing_lifespan,
    )

    with pytest.raises(BootstrapHealthLifespanShutdownError) as captured:
        async with lifespan(app):
            pass

    failures = captured.value.report.failures

    assert len(failures) == 1
    assert failures[0].operation == "existing_lifespan_exit"


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

    with pytest.raises(TypeError, match="async context manager"):
        async with lifespan(app):
            pass


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
