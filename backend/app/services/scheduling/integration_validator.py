
"""Structural integration validation for the scheduling subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ComponentRequirement:
    """Required callable interface for an integration component."""

    component: str
    methods: tuple[str, ...]
    attributes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ComponentValidation:
    """Validation result for a single component."""

    component: str
    valid: bool
    missing_methods: tuple[str, ...]
    missing_attributes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntegrationValidationReport:
    """Combined result of scheduling component validation."""

    valid: bool
    components_checked: int
    components_valid: int
    components_invalid: int
    results: tuple[ComponentValidation, ...]

    @property
    def errors(self) -> tuple[str, ...]:
        """Return human-readable interface validation errors."""
        messages: list[str] = []

        for result in self.results:
            if result.missing_methods:
                messages.append(
                    f"{result.component}: missing methods: "
                    + ", ".join(result.missing_methods)
                )

            if result.missing_attributes:
                messages.append(
                    f"{result.component}: missing attributes: "
                    + ", ".join(result.missing_attributes)
                )

        return tuple(messages)


class SchedulingIntegrationValidator:
    """Validate component interfaces before scheduler integration."""

    DEFAULT_REQUIREMENTS = (
        ComponentRequirement(
            component="scheduler_manager",
            methods=(
                "create_job",
                "update_job",
                "delete_job",
                "enable_job",
                "disable_job",
                "list_jobs",
                "restore_jobs",
                "start",
                "shutdown",
            ),
            attributes=("scheduler",),
        ),
        ComponentRequirement(
            component="task_registry",
            methods=(
                "register",
                "get",
                "get_optional",
                "unregister",
                "contains",
                "names",
                "get_all",
            ),
        ),
        ComponentRequirement(
            component="job_store",
            methods=(
                "add",
                "get",
                "list_all",
                "update",
                "delete",
                "close",
            ),
        ),
        ComponentRequirement(
            component="scheduler",
            methods=(
                "add_job",
                "get_job",
                "get_jobs",
                "remove_job",
                "start",
                "shutdown",
                "pause",
                "resume",
            ),
        ),
    )

    def __init__(
        self,
        requirements: Iterable[ComponentRequirement] | None = None,
    ) -> None:
        selected = (
            tuple(requirements)
            if requirements is not None
            else self.DEFAULT_REQUIREMENTS
        )

        if not selected:
            raise ValueError(
                "At least one component requirement is required"
            )

        names = [requirement.component for requirement in selected]

        if len(names) != len(set(names)):
            raise ValueError(
                "Component requirement names must be unique"
            )

        for requirement in selected:
            if not requirement.component.strip():
                raise ValueError(
                    "Component names must not be empty"
                )

            if len(requirement.methods) != len(set(requirement.methods)):
                raise ValueError(
                    f"Duplicate method requirement for "
                    f"{requirement.component}"
                )

            if len(requirement.attributes) != len(
                set(requirement.attributes)
            ):
                raise ValueError(
                    f"Duplicate attribute requirement for "
                    f"{requirement.component}"
                )

        self._requirements = selected

    @staticmethod
    def _validate_component(
        name: str,
        instance: Any,
        requirement: ComponentRequirement,
    ) -> ComponentValidation:
        missing_methods = tuple(
            method
            for method in requirement.methods
            if not callable(getattr(instance, method, None))
        )

        missing_attributes = tuple(
            attribute
            for attribute in requirement.attributes
            if not hasattr(instance, attribute)
        )

        return ComponentValidation(
            component=name,
            valid=not missing_methods and not missing_attributes,
            missing_methods=missing_methods,
            missing_attributes=missing_attributes,
        )

    def validate(
        self,
        components: dict[str, Any],
    ) -> IntegrationValidationReport:
        """Validate supplied instances against configured requirements."""
        if not isinstance(components, dict):
            raise TypeError("components must be a dictionary")

        results: list[ComponentValidation] = []

        for requirement in self._requirements:
            name = requirement.component
            instance = components.get(name)

            if instance is None:
                results.append(
                    ComponentValidation(
                        component=name,
                        valid=False,
                        missing_methods=requirement.methods,
                        missing_attributes=requirement.attributes,
                    )
                )
                continue

            results.append(
                self._validate_component(
                    name,
                    instance,
                    requirement,
                )
            )

        valid_count = sum(result.valid for result in results)
        invalid_count = len(results) - valid_count

        return IntegrationValidationReport(
            valid=invalid_count == 0,
            components_checked=len(results),
            components_valid=valid_count,
            components_invalid=invalid_count,
            results=tuple(results),
        )

    def validate_or_raise(
        self,
        components: dict[str, Any],
    ) -> IntegrationValidationReport:
        """Validate components and raise when any contract is incomplete."""
        report = self.validate(components)

        if not report.valid:
            details = "; ".join(report.errors)

            raise SchedulingIntegrationError(
                "Scheduling integration validation failed: "
                + details
            )

        return report


class SchedulingIntegrationError(RuntimeError):
    """Raised when scheduling components fail integration validation."""
