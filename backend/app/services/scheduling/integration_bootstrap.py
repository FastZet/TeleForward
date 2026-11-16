
"""Bootstrap orchestration for the scheduling subsystem."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.services.scheduling.integration_context import (
    SchedulingIntegrationContext,
    SchedulingIntegrationContextError,
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
    """Result of a scheduling integration bootstrap operation."""

    state: BootstrapState
    context_created: bool
    validation_report: IntegrationValidationReport | None
    error: str | None = None


ComponentFactory = Callable[[], Any | Awaitable[Any]]


class SchedulingIntegrationBootstrap:
    """Construct and validate scheduling components.

    The bootstrap does not start the scheduler. Scheduler activation
    remains the responsibility of SchedulerLifecycle.
    """

    REQUIRED_COMPONENTS = (
        "scheduler_manager",
        "task_registry",
        "job_store",
    )

    OPTIONAL_COMPONENTS = (
        "scheduler",
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
        unknown = set(factories) - (
            set(self.REQUIRED_COMPONENTS)
            | set(self.OPTIONAL_COMPONENTS)
        )

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

        self._factories = dict(factories)
        self._validator = validator

        self._manager_method_aliases = manager_method_aliases
        self._manager_attribute_aliases = manager_attribute_aliases
        self._registry_method_aliases = registry_method_aliases
        self._job_store_method_aliases = job_store_method_aliases
        self._scheduler_method_aliases = scheduler_method_aliases

        self._state = BootstrapState.NOT_STARTED
        self._context: SchedulingIntegrationContext | None = None
        self._report: BootstrapReport | None = None

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

    async def _build_components(self) -> dict[str, Any]:
        components: dict[str, Any] = {}

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

        return components

    async def bootstrap(self) -> BootstrapReport:
        """Build components and create a validated integration context."""
        if self._state is BootstrapState.READY:
            return self._report  # type: ignore[return-value]

        if self._state is BootstrapState.INITIALISING:
            raise SchedulingBootstrapError(
                "Scheduling bootstrap is already running"
            )

        if self._state is BootstrapState.CLOSED:
            raise SchedulingBootstrapError(
                "Closed scheduling bootstrap cannot be restarted"
            )

        self._state = BootstrapState.INITIALISING
        self._context = None

        try:
            components = await self._build_components()

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

        except Exception as exc:
            self._state = BootstrapState.FAILED
            self._context = None

            self._report = BootstrapReport(
                state=BootstrapState.FAILED,
                context_created=False,
                validation_report=None,
                error=str(exc),
            )

            logger.exception(
                "Scheduling integration bootstrap failed"
            )

            raise SchedulingBootstrapError(
                "Failed to bootstrap scheduling integration"
            ) from exc

    def close(self) -> None:
        """Close the bootstrap and release its context reference.

        This method does not shut down the scheduler or close the job
        store. Those operations belong to the lifecycle owner.
        """
        if self._state is BootstrapState.INITIALISING:
            raise SchedulingBootstrapError(
                "Cannot close bootstrap during initialisation"
            )

        self._context = None
        self._state = BootstrapState.CLOSED

        self._report = BootstrapReport(
            state=BootstrapState.CLOSED,
            context_created=False,
            validation_report=None,
        )

        logger.info("Scheduling integration bootstrap closed")
