
"""Structural integration validation for the scheduling subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.services.scheduling.integration_contracts import (
    DEFAULT_SCHEDULING_CONTRACTS,
    InterfaceContract,
)


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


class SchedulingIntegrationError(RuntimeError):
    """Raised when scheduling components fail integration validation."""


class SchedulingIntegrationValidator:
    """Validate component interfaces before scheduler integration."""

    DEFAULT_REQUIREMENTS = tuple(
        ComponentRequirement(
            component=contract.name,
            methods=contract.required_methods,
            attributes=contract.required_attributes,
        )
        for contract in DEFAULT_SCHEDULING_CONTRACTS
    )

    def __init__(
        self,
        requirements: Iterable[
            ComponentRequirement | InterfaceContract
        ] | None = None,
    ) -> None:
        selected = (
            self.DEFAULT_REQUIREMENTS
            if requirements is None
            else tuple(
                self._normalise_requirement(requirement)
                for requirement in requirements
            )
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

            if len(requirement.methods) != len(
                set(requirement.methods)
            ):
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
    def _normalise_requirement(
        requirement: ComponentRequirement | InterfaceContract,
    ) -> ComponentRequirement:
        """Convert supported contract types into validator requirements."""
        if isinstance(requirement, ComponentRequirement):
            return requirement

        if isinstance(requirement, InterfaceContract):
            return ComponentRequirement(
                component=requirement.name,
                methods=requirement.required_methods,
                attributes=requirement.required_attributes,
            )

        raise TypeError(
            "Requirements must be ComponentRequirement or "
            "InterfaceContract instances"
        )

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
