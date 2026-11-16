
"""Shared integration context for the scheduling subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from app.services.scheduling.component_adapters import (
    ComponentAdapterError,
    JobStoreAdapter,
    SchedulerEngineAdapter,
    SchedulerManagerAdapter,
    TaskRegistryAdapter,
)
from app.services.scheduling.integration_validator import (
    IntegrationValidationReport,
    SchedulingIntegrationError,
    SchedulingIntegrationValidator,
)


class SchedulingIntegrationContextError(RuntimeError):
    """Raised when scheduling components cannot be assembled."""


@dataclass(frozen=True, slots=True)
class SchedulingIntegrationContext:
    """Validated collection of scheduling subsystem components."""

    scheduler_manager: SchedulerManagerAdapter
    task_registry: TaskRegistryAdapter
    job_store: JobStoreAdapter
    scheduler: SchedulerEngineAdapter
    validation_report: IntegrationValidationReport

    @classmethod
    def create(
        cls,
        *,
        scheduler_manager: Any,
        task_registry: Any,
        job_store: Any,
        scheduler: Any | None = None,
        validator: SchedulingIntegrationValidator | None = None,
        manager_method_aliases: Mapping[str, str] | None = None,
        manager_attribute_aliases: Mapping[str, str] | None = None,
        registry_method_aliases: Mapping[str, str] | None = None,
        job_store_method_aliases: Mapping[str, str] | None = None,
        scheduler_method_aliases: Mapping[str, str] | None = None,
    ) -> SchedulingIntegrationContext:
        """Adapt and validate the scheduling components.

        If scheduler is omitted, the scheduler exposed by the manager
        is used. If supplied, it must be the identical object.
        """
        try:
            manager_adapter = SchedulerManagerAdapter(
                scheduler_manager,
                method_aliases=manager_method_aliases,
                attribute_aliases=manager_attribute_aliases,
            )

            manager_scheduler = manager_adapter.scheduler

            selected_scheduler = (
                manager_scheduler
                if scheduler is None
                else scheduler
            )

            if selected_scheduler is not manager_scheduler:
                raise SchedulingIntegrationContextError(
                    "The supplied scheduler is not the scheduler "
                    "exposed by the scheduler manager"
                )

            registry_adapter = TaskRegistryAdapter(
                task_registry,
                method_aliases=registry_method_aliases,
            )

            job_store_adapter = JobStoreAdapter(
                job_store,
                method_aliases=job_store_method_aliases,
            )

            scheduler_adapter = SchedulerEngineAdapter(
                selected_scheduler,
                method_aliases=scheduler_method_aliases,
            )

        except ComponentAdapterError as exc:
            raise SchedulingIntegrationContextError(
                "Failed to adapt scheduling components"
            ) from exc

        components = {
            "scheduler_manager": manager_adapter,
            "task_registry": registry_adapter,
            "job_store": job_store_adapter,
            "scheduler": scheduler_adapter,
        }

        selected_validator = (
            validator
            if validator is not None
            else SchedulingIntegrationValidator()
        )

        if not isinstance(
            selected_validator,
            SchedulingIntegrationValidator,
        ):
            raise TypeError(
                "validator must be a SchedulingIntegrationValidator"
            )

        try:
            report = selected_validator.validate_or_raise(components)
        except SchedulingIntegrationError as exc:
            raise SchedulingIntegrationContextError(
                "Scheduling component validation failed"
            ) from exc

        return cls(
            scheduler_manager=manager_adapter,
            task_registry=registry_adapter,
            job_store=job_store_adapter,
            scheduler=scheduler_adapter,
            validation_report=report,
        )

    @property
    def is_validated(self) -> bool:
        """Return whether structural validation succeeded."""
        return self.validation_report.valid

    @property
    def components(self) -> Mapping[str, Any]:
        """Return an immutable mapping of adapted components."""
        return MappingProxyType({
            "scheduler_manager": self.scheduler_manager,
            "task_registry": self.task_registry,
            "job_store": self.job_store,
            "scheduler": self.scheduler,
        })

    def get_component(self, name: str) -> Any:
        """Retrieve an adapted component by its canonical name."""
        try:
            return self.components[name]
        except KeyError as exc:
            raise KeyError(
                f"Unknown scheduling component: {name}"
            ) from exc

    def get_underlying_component(self, name: str) -> Any:
        """Retrieve the original component behind an adapter."""
        return self.get_component(name).component

    def revalidate(
        self,
        validator: SchedulingIntegrationValidator | None = None,
    ) -> IntegrationValidationReport:
        """Recheck the current adapted component interfaces."""
        selected_validator = (
            validator
            if validator is not None
            else SchedulingIntegrationValidator()
        )

        if not isinstance(
            selected_validator,
            SchedulingIntegrationValidator,
        ):
            raise TypeError(
                "validator must be a SchedulingIntegrationValidator"
            )

        try:
            # The validator currently accepts a dictionary. Convert the
            # immutable public mapping into a fresh validation snapshot.
            return selected_validator.validate_or_raise(
                dict(self.components)
            )
        except SchedulingIntegrationError as exc:
            raise SchedulingIntegrationContextError(
                "Scheduling component revalidation failed"
            ) from exc
