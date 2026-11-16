
"""Configurable adapters for scheduling subsystem components."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from app.services.scheduling.integration_contracts import (
    InterfaceContract,
    get_contract,
)


class ComponentAdapterError(RuntimeError):
    """Raised when a component cannot satisfy its adapter contract."""


class ComponentAdapter:
    """Expose a component through a canonical interface contract."""

    def __init__(
        self,
        component: Any,
        contract: InterfaceContract,
        *,
        method_aliases: Mapping[str, str] | None = None,
        attribute_aliases: Mapping[str, str] | None = None,
    ) -> None:
        if component is None:
            raise TypeError("component must not be None")

        if not isinstance(contract, InterfaceContract):
            raise TypeError("contract must be an InterfaceContract")

        self._component = component
        self._contract = contract

        self._method_aliases = self._validate_aliases(
            method_aliases or {},
            contract.required_methods,
            "method",
        )

        self._attribute_aliases = self._validate_aliases(
            attribute_aliases or {},
            contract.required_attributes,
            "attribute",
        )

        self._validate_component()

    @staticmethod
    def _validate_aliases(
        aliases: Mapping[str, str],
        allowed_names: tuple[str, ...],
        alias_type: str,
    ) -> Mapping[str, str]:
        if not isinstance(aliases, Mapping):
            raise TypeError(f"{alias_type}_aliases must be a mapping")

        validated: dict[str, str] = {}

        for canonical_name, actual_name in aliases.items():
            if canonical_name not in allowed_names:
                raise ComponentAdapterError(
                    f"Unknown canonical {alias_type}: {canonical_name}"
                )

            if not isinstance(actual_name, str) or not actual_name.strip():
                raise ValueError(
                    f"Invalid underlying {alias_type} name "
                    f"for {canonical_name}"
                )

            validated[canonical_name] = actual_name

        return MappingProxyType(validated)

    def _actual_method_name(self, canonical_name: str) -> str:
        return self._method_aliases.get(
            canonical_name,
            canonical_name,
        )

    def _actual_attribute_name(self, canonical_name: str) -> str:
        return self._attribute_aliases.get(
            canonical_name,
            canonical_name,
        )

    def _validate_component(self) -> None:
        missing_methods: list[str] = []
        missing_attributes: list[str] = []

        for method in self._contract.required_methods:
            actual_name = self._actual_method_name(method)

            if not callable(getattr(self._component, actual_name, None)):
                missing_methods.append(
                    f"{method} -> {actual_name}"
                )

        for attribute in self._contract.required_attributes:
            actual_name = self._actual_attribute_name(attribute)

            if not hasattr(self._component, actual_name):
                missing_attributes.append(
                    f"{attribute} -> {actual_name}"
                )

        if missing_methods or missing_attributes:
            details: list[str] = []

            if missing_methods:
                details.append(
                    "missing methods: " + ", ".join(missing_methods)
                )

            if missing_attributes:
                details.append(
                    "missing attributes: "
                    + ", ".join(missing_attributes)
                )

            raise ComponentAdapterError(
                f"Component does not satisfy contract "
                f"'{self._contract.name}': " + "; ".join(details)
            )

    @property
    def component(self) -> Any:
        """Return the underlying component."""
        return self._component

    @property
    def contract(self) -> InterfaceContract:
        """Return the adapter's interface contract."""
        return self._contract

    def __getattr__(self, name: str) -> Any:
        if name in self._contract.required_methods:
            actual_name = self._actual_method_name(name)
            return getattr(self._component, actual_name)

        if name in self._contract.required_attributes:
            actual_name = self._actual_attribute_name(name)
            return getattr(self._component, actual_name)

        raise AttributeError(
            f"{type(self).__name__!s} has no exposed attribute {name!r}"
        )


class SchedulerManagerAdapter(ComponentAdapter):
    """Adapter for the scheduling manager."""

    def __init__(
        self,
        component: Any,
        *,
        method_aliases: Mapping[str, str] | None = None,
        attribute_aliases: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            component,
            get_contract("scheduler_manager"),
            method_aliases=method_aliases,
            attribute_aliases=attribute_aliases,
        )


class TaskRegistryAdapter(ComponentAdapter):
    """Adapter for the scheduled task registry."""

    def __init__(
        self,
        component: Any,
        *,
        method_aliases: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            component,
            get_contract("task_registry"),
            method_aliases=method_aliases,
        )


class JobStoreAdapter(ComponentAdapter):
    """Adapter for the persistent scheduled job store."""

    def __init__(
        self,
        component: Any,
        *,
        method_aliases: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            component,
            get_contract("job_store"),
            method_aliases=method_aliases,
        )


class SchedulerEngineAdapter(ComponentAdapter):
    """Adapter for the underlying scheduling engine."""

    def __init__(
        self,
        component: Any,
        *,
        method_aliases: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            component,
            get_contract("scheduler"),
            method_aliases=method_aliases,
        )


def adapt_component(
    component_name: str,
    component: Any,
    *,
    method_aliases: Mapping[str, str] | None = None,
    attribute_aliases: Mapping[str, str] | None = None,
) -> ComponentAdapter:
    """Create the appropriate adapter for a canonical component name."""
    adapters = {
        "scheduler_manager": SchedulerManagerAdapter,
        "task_registry": TaskRegistryAdapter,
        "job_store": JobStoreAdapter,
        "scheduler": SchedulerEngineAdapter,
    }

    adapter_type = adapters.get(component_name)

    if adapter_type is None:
        raise ValueError(
            f"Unsupported scheduling component: {component_name}"
        )

    if adapter_type is not SchedulerManagerAdapter and attribute_aliases:
        raise ValueError(
            "Attribute aliases are only supported for scheduler_manager"
        )

    return adapter_type(
        component,
        method_aliases=method_aliases,
        **(
            {"attribute_aliases": attribute_aliases}
            if adapter_type is SchedulerManagerAdapter
            else {}
        ),
    )
