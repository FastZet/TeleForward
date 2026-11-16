
"""Lifecycle ownership and partial-startup regression tests."""

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
async def test_existing_lifespan_exit_runs_after_successful_entry(
    app: FastAPI,
    install_fake_integration: None,
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

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
    )

    async with lifespan(app):
        events.append("application")

    assert events == [
        "entered",
        "application",
        "exited",
    ]


@pytest.mark.asyncio
async def test_existing_lifespan_exit_is_not_called_when_entry_fails(
    app: FastAPI,
) -> None:
    events: list[str] = []

    class FailingContext:
        async def __aenter__(self) -> None:
            events.append("enter")
            raise RuntimeError("entry failed")

        async def __aexit__(
            self,
            exc_type,
            exc,
            traceback,
        ) -> bool:
            events.append("exit")
            return False

    def factory(_app: FastAPI) -> FailingContext:
        return FailingContext()

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=factory,
    )

    with pytest.raises(RuntimeError, match="entry failed"):
        async with lifespan(app):
            pytest.fail("Application body must not execute")

    assert events == ["enter"]


@pytest.mark.asyncio
async def test_cancellation_during_existing_lifespan_entry_is_propagated(
    app: FastAPI,
) -> None:
    entry_started = asyncio.Event()
    allow_entry_to_finish = asyncio.Event()
    exit_called = asyncio.Event()

    class BlockingContext:
        async def __aenter__(self) -> None:
            entry_started.set()
            await allow_entry_to_finish.wait()

        async def __aexit__(
            self,
            exc_type,
            exc,
            traceback,
        ) -> bool:
            exit_called.set()
            return False

    def factory(_app: FastAPI) -> BlockingContext:
        return BlockingContext()

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=factory,
    )

    async def run() -> None:
        async with lifespan(app):
            pytest.fail("Application body must not execute")

    task = asyncio.create_task(run())

    await asyncio.wait_for(entry_started.wait(), timeout=2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert not exit_called.is_set()


@pytest.mark.asyncio
async def test_cancelled_entry_does_not_run_shutdown_callbacks(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    entry_started = asyncio.Event()
    shutdown_events: list[str] = []

    class BlockingContext:
        async def __aenter__(self) -> None:
            entry_started.set()
            await asyncio.Event().wait()

        async def __aexit__(
            self,
            exc_type,
            exc,
            traceback,
        ) -> bool:
            return False

    def factory(_app: FastAPI) -> BlockingContext:
        return BlockingContext()

    async def before_shutdown(_app: FastAPI) -> None:
        shutdown_events.append("before")

    async def after_shutdown(_app: FastAPI) -> None:
        shutdown_events.append("after")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=factory,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    async def run() -> None:
        async with lifespan(app):
            pass

    task = asyncio.create_task(run())

    await asyncio.wait_for(entry_started.wait(), timeout=2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert shutdown_events == []


@pytest.mark.asyncio
async def test_before_start_failure_exits_existing_lifespan(
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

    async def before_start(_app: FastAPI) -> None:
        events.append("before_start")
        raise RuntimeError("before-start failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
        before_start=before_start,
    )

    with pytest.raises(RuntimeError, match="before-start failure"):
        async with lifespan(app):
            pass

    assert events == [
        "entered",
        "before_start",
        "exited",
    ]


@pytest.mark.asyncio
async def test_integration_installation_failure_exits_existing_lifespan(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
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

    async def failing_install(
        _app: FastAPI,
        service=None,
    ):
        events.append("install")
        raise RuntimeError("integration installation failed")

    monkeypatch.setattr(
        integration_module,
        "_install_integration",
        failing_install,
    )

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
    )

    with pytest.raises(
        RuntimeError,
        match="integration installation failed",
    ):
        async with lifespan(app):
            pytest.fail("Application body must not execute")

    assert events == [
        "entered",
        "install",
        "exited",
    ]


@pytest.mark.asyncio
async def test_after_start_failure_runs_shutdown_callbacks(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    events: list[str] = []

    async def after_start(_app: FastAPI) -> None:
        events.append("after_start")
        raise RuntimeError("after-start failure")

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before_shutdown")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after_shutdown")

    lifespan = create_integrated_bootstrap_health_lifespan(
        after_start=after_start,
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    with pytest.raises(RuntimeError, match="after-start failure"):
        async with lifespan(app):
            pass

    assert events == [
        "after_start",
        "before_shutdown",
        "after_shutdown",
    ]


@pytest.mark.asyncio
async def test_wrong_integration_type_does_not_mark_integration_installed(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedIntegration:
        pass

    monkeypatch.setattr(
        integration_module,
        "SchedulingBootstrapHealthAPIIntegration",
        FakeIntegration,
    )

    async def wrong_install(
        _app: FastAPI,
        service=None,
    ) -> UnexpectedIntegration:
        return UnexpectedIntegration()

    monkeypatch.setattr(
        integration_module,
        "_install_integration",
        wrong_install,
    )

    events: list[str] = []

    async def before_shutdown(_app: FastAPI) -> None:
        events.append("before")

    async def after_shutdown(_app: FastAPI) -> None:
        events.append("after")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=before_shutdown,
        after_shutdown=after_shutdown,
    )

    with pytest.raises(
        RuntimeError,
        match="invalid integration",
    ):
        async with lifespan(app):
            pass

    assert events == []


@pytest.mark.asyncio
async def test_existing_lifespan_suppression_does_not_skip_shutdown_errors(
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

    async def failing_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("shutdown failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=suppressing_lifespan,
        before_shutdown=failing_shutdown,
    )

    with pytest.raises(BootstrapHealthLifespanShutdownError):
        async with lifespan(app):
            raise ValueError("application failure")

    assert events == ["suppressed"]


@pytest.mark.asyncio
async def test_primary_cancellation_survives_existing_lifespan_suppression(
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
            events.append("suppression_attempted")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=suppressing_lifespan,
    )

    with pytest.raises(asyncio.CancelledError):
        async with lifespan(app):
            raise asyncio.CancelledError("primary cancellation")

    assert events == ["suppression_attempted"]


@pytest.mark.asyncio
async def test_cleanup_cancellation_is_preserved_after_successful_application(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    async def cancelling_shutdown(_app: FastAPI) -> None:
        raise asyncio.CancelledError("cleanup cancellation")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=cancelling_shutdown,
    )

    with pytest.raises(CleanupCancelledError) as captured:
        async with lifespan(app):
            pass

    assert captured.value.report.cancellation_count == 1


@pytest.mark.asyncio
async def test_external_cancellation_does_not_interrupt_blocked_cleanup(
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

    with pytest.raises(CleanupCancelledError):
        await task

    assert cleanup_completed.is_set()


@pytest.mark.asyncio
async def test_existing_lifespan_exit_failure_is_recorded(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    @asynccontextmanager
    async def failing_existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        yield
        raise RuntimeError("existing exit failed")

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


def test_non_callable_callbacks_are_rejected() -> None:
    with pytest.raises(TypeError, match="callbacks"):
        create_integrated_bootstrap_health_lifespan(
            before_start="not callable",
        )


def test_non_callable_existing_lifespan_is_rejected() -> None:
    with pytest.raises(TypeError, match="existing_lifespan"):
        create_integrated_bootstrap_health_lifespan(
            existing_lifespan="not callable",
        )
