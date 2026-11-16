
"""Canonical interface contracts for scheduling subsystem integration.

These contracts describe the structural interfaces expected by the
integration layer. They do not replace concrete implementations or
guarantee behavioural compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InterfaceContract:
    """Structural interface expected from a subsystem component."""

    name: str
    required_methods: tuple[str, ...]
    required_attributes: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Contract name must not be empty")

        if len(self.required_methods) != len(
            set(self.required_methods)
        ):
            raise ValueError(
                f"Duplicate methods in contract: {self.name}"
            )

        if len(self.required_attributes) != len(
            set(self.required_attributes)
        ):
            raise ValueError(
                f"Duplicate attributes in contract: {self.name}"
            )

        for method in self.required_methods:
            if not isinstance(method, str) or not method.strip():
                raise ValueError(
                    f"Invalid method name in contract: {self.name}"
                )

        for attribute in self.required_attributes:
            if not isinstance(attribute, str) or not attribute.strip():
                raise ValueError(
                    f"Invalid attribute name in contract: {self.name}"
                )


SCHEDULER_MANAGER_CONTRACT = InterfaceContract(
    name="scheduler_manager",
    required_methods=(
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
    required_attributes=("scheduler",),
    description=(
        "Coordinates persisted job definitions with the scheduler."
    ),
)

TASK_REGISTRY_CONTRACT = InterfaceContract(
    name="task_registry",
    required_methods=(
        "register",
        "get",
        "get_optional",
        "unregister",
        "contains",
        "names",
        "get_all",
    ),
    description=(
        "Stores and retrieves registered scheduled task implementations."
    ),
)

JOB_STORE_CONTRACT = InterfaceContract(
    name="job_store",
    required_methods=(
        "add",
        "get",
        "list_all",
        "update",
        "delete",
        "close",
    ),
    description=(
        "Persists and retrieves scheduled job definitions."
    ),
)

SCHEDULER_CONTRACT = InterfaceContract(
    name="scheduler",
    required_methods=(
        "add_job",
        "get_job",
        "get_jobs",
        "remove_job",
        "start",
        "shutdown",
        "pause",
        "resume",
    ),
    description=(
        "Provides the scheduling engine operations used by the manager."
    ),
)

DEFAULT_SCHEDULING_CONTRACTS: tuple[InterfaceContract, ...] = (
    SCHEDULER_MANAGER_CONTRACT,
    TASK_REGISTRY_CONTRACT,
    JOB_STORE_CONTRACT,
    SCHEDULER_CONTRACT,
)


def get_contract(name: str) -> InterfaceContract:
    """Return a contract by its canonical component name."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Contract name must not be empty")

    for contract in DEFAULT_SCHEDULING_CONTRACTS:
        if contract.name == name:
            return contract

    raise KeyError(f"Unknown scheduling contract: {name}")


def get_all_contracts() -> tuple[InterfaceContract, ...]:
    """Return all default scheduling contracts."""
    return DEFAULT_SCHEDULING_CONTRACTS


def contracts_as_mapping() -> dict[str, InterfaceContract]:
    """Return contracts indexed by component name."""
    return {
        contract.name: contract
        for contract in DEFAULT_SCHEDULING_CONTRACTS
    }
