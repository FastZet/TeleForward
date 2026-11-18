
"""Tests for observable bootstrap health lifespan execution state."""

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
    BootstrapHealthLifespanIntegrationError,
    BootstrapHealthLifespanShutdownError,
    LifespanExecutionState,
    LifespanPhase,
    create_integrated_bootstrap_health_lifespan,
    get_lifespan_execution_state,
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
        "BootstrapHealthAPIIntegration",
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
async def test_initial_and_final_lifecycle_phases(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    async with lifespan(app):
        state = get_lifespan_execution_state(app)

        assert state is not None
        assert state.phase == LifespanPhase.RUNNING

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.phase == LifespanPhase.STOPPED


@pytest.mark.asyncio
async def test_successful_lifecycle_records_expected_phase_history(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    async with lifespan(app):
        pass

    state = get_lifespan_execution_state(app)

    assert state is not None

    phases = [phase for phase, _timestamp in state.phase_history]

    assert phases == [
        LifespanPhase.INITIALISING,
        LifespanPhase.INTEGRATION_INSTALLED,
        LifespanPhase.RUNNING,
        LifespanPhase.CLEANING_UP,
        LifespanPhase.STOPPED,
    ]


@pytest.mark.asyncio
async def test_existing_lifespan_phase_is_recorded(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        yield

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
    )

    async with lifespan(app):
        state = get_lifespan_execution_state(app)

        assert state is not None
        assert (
            state.phase
            == LifespanPhase.RUNNING
        )

    state = get_lifespan_execution_state(app)

    assert state is not None

    phases = [phase for phase, _ in state.phase_history]

    assert LifespanPhase.EXISTING_LIFESPAN_ENTERED in phases


@pytest.mark.asyncio
async def test_state_records_successful_context_ownership(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    @asynccontextmanager
    async def existing_lifespan(
        _app: FastAPI,
    ) -> AsyncIterator[None]:
        yield

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=existing_lifespan,
    )

    async with lifespan(app):
        state = get_lifespan_execution_state(app)

        assert state is not None
        assert state.existing_context_entered is True

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.existing_context_entered is True


@pytest.mark.asyncio
async def test_state_records_integration_installation(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    async with lifespan(app):
        state = get_lifespan_execution_state(app)

        assert state is not None
        assert state.integration_installed is True


@pytest.mark.asyncio
async def test_startup_failure_records_failed_phase(
    app: FastAPI,
) -> None:
    async def failing_start(_app: FastAPI) -> None:
        raise RuntimeError("startup failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_start=failing_start,
    )

    with pytest.raises(RuntimeError, match="startup failure"):
        async with lifespan(app):
            pass

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.phase == LifespanPhase.FAILED
    assert state.integration_installed is False
    assert state.primary_error_type == "RuntimeError"
    assert state.primary_error_message == "startup failure"


@pytest.mark.asyncio
async def test_failed_context_entry_does_not_claim_ownership(
    app: FastAPI,
) -> None:
    class FailingContext:
        async def __aenter__(self) -> None:
            raise RuntimeError("entry failed")

        async def __aexit__(
            self,
            exc_type,
            exc,
            traceback,
        ) -> bool:
            pytest.fail("Exit must not be called")

    def factory(_app: FastAPI) -> FailingContext:
        return FailingContext()

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=factory,
    )

    with pytest.raises(RuntimeError, match="entry failed"):
        async with lifespan(app):
            pass

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.existing_context_entered is False
    assert state.phase == LifespanPhase.FAILED


@pytest.mark.asyncio
async def test_primary_exception_details_are_recorded(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    with pytest.raises(ValueError, match="application failure"):
        async with lifespan(app):
            raise ValueError("application failure")

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.primary_error_type == "ValueError"
    assert state.primary_error_message == "application failure"
    assert state.phase == LifespanPhase.FAILED


@pytest.mark.asyncio
async def test_suppressed_exception_is_recorded(
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

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=suppressing_lifespan,
    )

    async with lifespan(app):
        raise ValueError("suppressed failure")

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.exception_suppressed is True
    assert state.phase == LifespanPhase.STOPPED
    assert state.primary_error_type == "ValueError"


@pytest.mark.asyncio
async def test_unsuppressed_exception_is_recorded(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    with pytest.raises(ValueError, match="application failure"):
        async with lifespan(app):
            raise ValueError("application failure")

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.exception_suppressed is False
    assert state.phase == LifespanPhase.FAILED


@pytest.mark.asyncio
async def test_cleanup_report_is_retained_after_successful_shutdown(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    async with lifespan(app):
        pass

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.cleanup_report is not None
    assert state.cleanup_report.succeeded is True
    assert state.cleanup_report.failures == ()


@pytest.mark.asyncio
async def test_cleanup_report_is_retained_after_shutdown_failure(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    async def failing_shutdown(_app: FastAPI) -> None:
        raise RuntimeError("shutdown failure")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=failing_shutdown,
    )

    with pytest.raises(BootstrapHealthLifespanShutdownError):
        async with lifespan(app):
            pass

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.cleanup_report is not None
    assert len(state.cleanup_report.failures) == 1
    assert state.phase == LifespanPhase.FAILED


@pytest.mark.asyncio
async def test_cleanup_cancellation_is_retained_in_state(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    async def cancelling_shutdown(_app: FastAPI) -> None:
        raise asyncio.CancelledError("cleanup cancellation")

    lifespan = create_integrated_bootstrap_health_lifespan(
        before_shutdown=cancelling_shutdown,
    )

    with pytest.raises(CleanupCancelledError):
        async with lifespan(app):
            pass

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.cleanup_report is not None
    assert state.cleanup_report.cancellation is not None
    assert state.phase == LifespanPhase.CANCELLED


@pytest.mark.asyncio
async def test_cleanup_cancellation_after_exception_suppression_is_retained(
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

    async def cancelling_shutdown(_app: FastAPI) -> None:
        raise asyncio.CancelledError("cleanup cancellation")

    lifespan = create_integrated_bootstrap_health_lifespan(
        existing_lifespan=suppressing_lifespan,
        before_shutdown=cancelling_shutdown,
    )

    with pytest.raises(CleanupCancelledError):
        async with lifespan(app):
            raise ValueError("suppressed application failure")

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.exception_suppressed is True
    assert state.cleanup_report is not None
    assert state.cleanup_report.cancellation is not None


@pytest.mark.asyncio
async def test_primary_cancellation_remains_primary(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    with pytest.raises(asyncio.CancelledError):
        async with lifespan(app):
            raise asyncio.CancelledError("primary cancellation")

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.primary_error_type == "CancelledError"
    assert state.phase == LifespanPhase.CANCELLED


@pytest.mark.asyncio
async def test_external_cancellation_during_cleanup_updates_final_state(
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

    state = get_lifespan_execution_state(app)

    assert state is not None
    assert state.cleanup_report is not None
    assert state.phase == LifespanPhase.CANCELLED


@pytest.mark.asyncio
async def test_state_history_timestamps_are_timezone_aware(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    async with lifespan(app):
        pass

    state = get_lifespan_execution_state(app)

    assert state is not None

    for _phase, timestamp in state.phase_history:
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset() is not None


@pytest.mark.asyncio
async def test_phase_history_is_chronological(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    async with lifespan(app):
        pass

    state = get_lifespan_execution_state(app)

    assert state is not None

    timestamps = [
        timestamp
        for _phase, timestamp in state.phase_history
    ]

    assert timestamps == sorted(timestamps)


def test_get_state_returns_none_before_lifespan_execution(
    app: FastAPI,
) -> None:
    assert get_lifespan_execution_state(app) is None


def test_get_state_rejects_invalid_application() -> None:
    with pytest.raises(TypeError, match="FastAPI"):
        get_lifespan_execution_state(object())


def test_execution_state_rejects_invalid_phase() -> None:
    state = LifespanExecutionState()

    with pytest.raises(TypeError, match="LifespanPhase"):
        state.transition("invalid")


def test_execution_state_records_error_without_retaining_exception() -> None:
    state = LifespanExecutionState()
    error = RuntimeError("example failure")

    state.record_primary_error(error)

    assert state.primary_error_type == "RuntimeError"
    assert state.primary_error_message == "example failure"


def test_execution_state_rejects_illegal_phase_transition() -> None:
    state = LifespanExecutionState()

    with pytest.raises(ValueError, match="Invalid lifespan phase"):
        state.transition(LifespanPhase.RUNNING)


@pytest.mark.asyncio
async def test_published_state_is_immutable_snapshot(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    async with lifespan(app):
        snapshot = get_lifespan_execution_state(app)
        assert snapshot is not None
        assert isinstance(snapshot.phase_history, tuple)

        with pytest.raises((AttributeError, TypeError)):
            snapshot.phase = LifespanPhase.FAILED  # type: ignore[misc]

        with pytest.raises((AttributeError, TypeError)):
            snapshot.phase_history += ()  # type: ignore[misc]


@pytest.mark.asyncio
async def test_repeated_lifespan_execution_replaces_terminal_snapshot(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()

    async with lifespan(app):
        first_snapshot = get_lifespan_execution_state(app)

    async with lifespan(app):
        second_snapshot = get_lifespan_execution_state(app)

    assert first_snapshot is not None
    assert second_snapshot is not None
    assert first_snapshot is not second_snapshot
    assert first_snapshot.phase == LifespanPhase.RUNNING
    assert second_snapshot.phase == LifespanPhase.RUNNING


@pytest.mark.asyncio
async def test_concurrent_lifespan_execution_is_rejected(
    app: FastAPI,
    install_fake_integration: None,
) -> None:
    lifespan = create_integrated_bootstrap_health_lifespan()
    first_context = lifespan(app)
    await first_context.__aenter__()

    try:
        with pytest.raises(
            BootstrapHealthLifespanIntegrationError,
            match="already executing",
        ):
            await lifespan(app).__aenter__()
    finally:
        await first_context.__aexit__(None, None, None)
