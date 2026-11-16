
"""Bootstrap orchestration for the scheduling subsystem."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from app.services.scheduling.integration_context import (
    SchedulingIntegrationContext,
)
from app.services.scheduling.integration_validator import (
    IntegrationValidationReport,
    SchedulingIntegrationValidator,
)


logger = logging.getLogger(__name__)


class BootstrapState(StrEnum):
    """Lifecycle state of the integration bootstrap."""

    NOT_STARTED = "not_started"
    INITIALISING = "initialising"
    READY = "ready"
    FAILED = "failed"
    CLOSED = "closed"


class SchedulingBootstrapError(RuntimeError):
    """Raised when scheduling bootstrap fails."""


@dataclass(frozen=True, slots=True)
class BootstrapReport:
    """Immutable result of a scheduling bootstrap operation."""

    state: BootstrapState
    context_created: bool
    validation_report: IntegrationValidationReport | None
    error: str | None = None
    cleanup_errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, BootstrapState):
            raise TypeError("state must be a BootstrapState")

        if not isinstance(self.context_created, bool):
            raise TypeError("context_created must be a bool")

        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string or None")

        if not isinstance(self.cleanup_errors, tuple):
            raise TypeError("cleanup_errors must be a tuple")

        if any(
            not isinstance(item, str)
            for item in self.cleanup_errors
        ):
            raise TypeError(
                "cleanup_errors must contain only strings"
            )


ComponentFactory = Callable[[], Any | Awaitable[Any]]
CleanupCallback = Callable[[Any], Any | Awaitable[Any]]


class SchedulingIntegrationBootstrap:
    """Construct, validate, and clean up scheduling components.

    Concurrent bootstrap calls are serialised. Successful concurrent
    callers reuse the same integration context.

    Cleanup callbacks execute in reverse construction order after
    bootstrap failure, cancellation, or asynchronous closure.

    The bootstrap does not start the scheduler.
    """

    REQUIRED_COMPONENTS = (
        "scheduler_manager",
        "task_registry",
        "job_store",
    )

    OPTIONAL_COMPONENTS = (
        "scheduler",
    )

    ALLOWED_COMPONENTS = frozenset(
        (*REQUIRED_COMPONENTS, *OPTIONAL_COMPONENTS)
    )

    def __init__(
        self,
        factories: Mapping[str, ComponentFactory],
        *,
        validator: SchedulingIntegrationValidator | None = None,
        manager_method_aliases: Mapping[str, str] | None = None,
        manager_attribute_aliases: Mapping[str, str] | None = None,
        registry_method_aliases: Mapping[str, str] | None = None,
        job_store_method_aliases: Mapping[str, str] | None = None,
        scheduler_method_aliases: Mapping[str, str] | None = None,
        cleanup_callbacks: Mapping[str, CleanupCallback] | None = None,
    ) -> None:
        if not isinstance(factories, Mapping):
            raise TypeError("factories must be a mapping")

        if validator is not None and not isinstance(
            validator,
            SchedulingIntegrationValidator,
        ):
            raise TypeError(
                "validator must be a SchedulingIntegrationValidator"
            )

        missing = set(self.REQUIRED_COMPONENTS) - set(factories)
        unknown = set(factories) - self.ALLOWED_COMPONENTS

        if missing:
            raise ValueError(
                "Missing required component factories: "
                + ", ".join(sorted(missing))
            )

        if unknown:
            raise ValueError(
                "Unknown component factories: "
                + ", ".join(sorted(unknown))
            )

        for name, factory in factories.items():
            if not callable(factory):
                raise TypeError(
                    f"Factory for {name!r} must be callable"
                )

        if cleanup_callbacks is None:
            cleanup_callbacks = {}

        if not isinstance(cleanup_callbacks, Mapping):
            raise TypeError("cleanup_callbacks must be a mapping")

        unknown_cleanup = (
            set(cleanup_callbacks) - self.ALLOWED_COMPONENTS
        )

        if unknown_cleanup:
            raise ValueError(
                "Unknown cleanup callback components: "
                + ", ".join(sorted(unknown_cleanup))
            )

        for name, callback in cleanup_callbacks.items():
            if not callable(callback):
                raise TypeError(
                    f"Cleanup callback for {name!r} must be callable"
                )

            if name not in factories:
                raise ValueError(
                    f"Cleanup callback for {name!r} has no factory"
                )

        self._factories = dict(factories)
        self._cleanup_callbacks = dict(cleanup_callbacks)
        self._validator = validator

        self._manager_method_aliases = manager_method_aliases
        self._manager_attribute_aliases = manager_attribute_aliases
        self._registry_method_aliases = registry_method_aliases
        self._job_store_method_aliases = job_store_method_aliases
        self._scheduler_method_aliases = scheduler_method_aliases

        self._state = BootstrapState.NOT_STARTED
        self._context: SchedulingIntegrationContext | None = None
        self._components: dict[str, Any] = {}
        self._report: BootstrapReport | None = None

        self._bootstrap_lock = asyncio.Lock()

    @property
    def state(self) -> BootstrapState:
        return self._state

    @property
    def context(self) -> SchedulingIntegrationContext:
        if self._context is None:
            raise SchedulingBootstrapError(
                "Scheduling integration context is not available"
            )

        return self._context

    @property
    def report(self) -> BootstrapReport | None:
        return self._report

    @property
    def components(self) -> Mapping[str, Any]:
        """Return a read-only snapshot of constructed components."""
        return MappingProxyType(dict(self._components))

    async def _invoke_cleanup(
        self,
        component_name: str,
        component: Any,
    ) -> None:
        callback = self._cleanup_callbacks.get(component_name)

        if callback is None:
            return

        result = callback(component)

        if inspect.isawaitable(result):
            await result

    async def _cleanup_components(
        self,
        components: Mapping[str, Any],
    ) -> list[str]:
        """Attempt cleanup for every component in reverse order."""
        errors: list[str] = []

        for name, component in reversed(tuple(components.items())):
            try:
                await self._invoke_cleanup(name, component)

            except asyncio.CancelledError:
                message = f"{name}: cleanup callback was cancelled"
                errors.append(message)

                logger.error(
                    "Cleanup callback was cancelled for %s",
                    name,
                )

            except Exception as exc:
                message = f"{name}: {exc}"
                errors.append(message)

                logger.exception(
                    "Cleanup failed for scheduling component %s",
                    name,
                )

        return errors

    async def _cleanup_resiliently(
        self,
        components: Mapping[str, Any],
    ) -> tuple[list[str], bool]:
        """Finish cleanup despite cancellation of the calling task."""
        cleanup_task = asyncio.create_task(
            self._cleanup_components(components),
            name="scheduling-bootstrap-cleanup",
        )

        cancellation_received = False

        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)

            except asyncio.CancelledError:
                cancellation_received = True

                logger.warning(
                    "Deferring cancellation until scheduling cleanup "
                    "has completed"
                )

            except Exception:
                break

        if cleanup_task.cancelled():
            return (
                ["cleanup coordinator was cancelled"],
                cancellation_received,
            )

        try:
            errors = cleanup_task.result()
        except Exception as exc:
            errors = [f"cleanup coordinator failed: {exc}"]

        return errors, cancellation_received

    async def _build_components(
        self,
        components: dict[str, Any],
    ) -> None:
        """Construct components directly into the tracking dictionary."""
        for name in (
            *self.REQUIRED_COMPONENTS,
            *self.OPTIONAL_COMPONENTS,
        ):
            factory = self._factories.get(name)

            if factory is None:
                continue

            component = factory()

            if inspect.isawaitable(component):
                component = await component

            if component is None:
                raise SchedulingBootstrapError(
                    f"Factory for {name!r} returned None"
                )

            components[name] = component

    def _record_failure(
        self,
        error: BaseException,
        cleanup_errors: list[str] | None = None,
    ) -> None:
        recorded_cleanup_errors = tuple(cleanup_errors or ())

        self._state = BootstrapState.FAILED
        self._context = None
        self._components = {}

        message = str(error)

        if recorded_cleanup_errors:
            message += (
                "; cleanup failures: "
                + "; ".join(recorded_cleanup_errors)
            )

        self._report = BootstrapReport(
            state=BootstrapState.FAILED,
            context_created=False,
            validation_report=None,
            error=message,
            cleanup_errors=recorded_cleanup_errors,
        )

    async def _bootstrap_locked(self) -> BootstrapReport:
        if self._state is BootstrapState.READY:
            if self._report is None:
                raise SchedulingBootstrapError(
                    "Bootstrap is READY without a result report"
                )
            return self._report

        if self._state is BootstrapState.CLOSED:
            raise SchedulingBootstrapError(
                "Closed scheduling bootstrap cannot be restarted"
            )

        self._state = BootstrapState.INITIALISING
        self._context = None
        self._components = {}
        self._report = None

        components: dict[str, Any] = {}

        try:
            await self._build_components(components)

            context = SchedulingIntegrationContext.create(
                scheduler_manager=components["scheduler_manager"],
                task_registry=components["task_registry"],
                job_store=components["job_store"],
                scheduler=components.get("scheduler"),
                validator=self._validator,
                manager_method_aliases=self._manager_method_aliases,
                manager_attribute_aliases=self._manager_attribute_aliases,
                registry_method_aliases=self._registry_method_aliases,
                job_store_method_aliases=self._job_store_method_aliases,
                scheduler_method_aliases=self._scheduler_method_aliases,
            )

            self._components = components
            self._context = context
            self._state = BootstrapState.READY

            self._report = BootstrapReport(
                state=BootstrapState.READY,
                context_created=True,
                validation_report=context.validation_report,
            )

            logger.info(
                "Scheduling integration bootstrap completed"
            )

            return self._report

        except asyncio.CancelledError as exc:
            cleanup_errors, _ = await self._cleanup_resiliently(
                components
            )

            self._record_failure(exc, cleanup_errors)

            logger.warning(
                "Scheduling integration bootstrap was cancelled"
            )
            raise

        except Exception as exc:
            cleanup_errors, cancellation_received = (
                await self._cleanup_resiliently(components)
            )

            self._record_failure(exc, cleanup_errors)

            if cancellation_received:
                logger.warning(
                    "Cancellation was received during failure cleanup; "
                    "preserving the original bootstrap exception"
                )

            logger.exception(
                "Scheduling integration bootstrap failed"
            )

            raise SchedulingBootstrapError(
                "Failed to bootstrap scheduling integration"
            ) from exc

        except BaseException as exc:
            cleanup_errors, _ = await self._cleanup_resiliently(
                components
            )

            self._record_failure(exc, cleanup_errors)
            raise

    async def bootstrap(self) -> BootstrapReport:
        """Build components and create a validated integration context."""
        async with self._bootstrap_lock:
            return await self._bootstrap_locked()

    async def aclose(self) -> None:
        """Clean up constructed components and close the bootstrap."""
        async with self._bootstrap_lock:
            if self._state is BootstrapState.CLOSED:
                return

            if self._state is BootstrapState.INITIALISING:
                raise SchedulingBootstrapError(
                    "Cannot close bootstrap during initialisation"
                )

            components = dict(self._components)

            cleanup_errors, cancellation_received = (
                await self._cleanup_resiliently(components)
            )

            self._components = {}
            self._context = None
            self._state = BootstrapState.CLOSED

            self._report = BootstrapReport(
                state=BootstrapState.CLOSED,
                context_created=False,
                validation_report=None,
                error=(
                    "; ".join(cleanup_errors)
                    if cleanup_errors
                    else None
                ),
                cleanup_errors=tuple(cleanup_errors),
            )

            if cancellation_received:
                raise asyncio.CancelledError

            if cleanup_errors:
                raise SchedulingBootstrapError(
                    "Bootstrap closed with cleanup failures: "
                    + "; ".join(cleanup_errors)
                )

            logger.info(
                "Scheduling integration bootstrap closed"
            )

    def close(self) -> None:
        """Release references without executing cleanup callbacks.

        Use aclose() when constructed resources must be released.
        """
        if self._state is BootstrapState.INITIALISING:
            raise SchedulingBootstrapError(
                "Cannot close bootstrap during initialisation"
            )

        self._context = None
        self._components = {}
        self._state = BootstrapState.CLOSED

        self._report = BootstrapReport(
            state=BootstrapState.CLOSED,
            context_created=False,
            validation_report=None,
        )

        logger.info(
            "Scheduling integration bootstrap references released"
        )
