
"""Tests for scheduling integration interface contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.services.scheduling.integration_contracts import (
    DEFAULT_SCHEDULING_CONTRACTS,
    JOB_STORE_CONTRACT,
    SCHEDULER_CONTRACT,
    SCHEDULER_MANAGER_CONTRACT,
    TASK_REGISTRY_CONTRACT,
    InterfaceContract,
    contracts_as_mapping,
    get_all_contracts,
    get_contract,
)


def test_default_contracts_contain_expected_components() -> None:
    names = {
        contract.name
        for contract in DEFAULT_SCHEDULING_CONTRACTS
    }

    assert names == {
        "scheduler_manager",
        "task_registry",
        "job_store",
        "scheduler",
    }


def test_default_contract_names_are_unique() -> None:
    names = [
        contract.name
        for contract in DEFAULT_SCHEDULING_CONTRACTS
    ]

    assert len(names) == len(set(names))


@pytest.mark.parametrize(
    ("contract", "expected_methods"),
    [
        (
            SCHEDULER_MANAGER_CONTRACT,
            {
                "create_job",
                "update_job",
                "delete_job",
                "enable_job",
                "disable_job",
                "list_jobs",
                "restore_jobs",
                "start",
                "shutdown",
            },
        ),
        (
            TASK_REGISTRY_CONTRACT,
            {
                "register",
                "get",
                "get_optional",
                "unregister",
                "contains",
                "names",
                "get_all",
            },
        ),
        (
            JOB_STORE_CONTRACT,
            {
                "add",
                "get",
                "list_all",
                "update",
                "delete",
                "close",
            },
        ),
        (
            SCHEDULER_CONTRACT,
            {
                "add_job",
                "get_job",
                "get_jobs",
                "remove_job",
                "start",
                "shutdown",
                "pause",
                "resume",
            },
        ),
    ],
)
def test_default_contract_methods(
    contract: InterfaceContract,
    expected_methods: set[str],
) -> None:
    assert set(contract.required_methods) == expected_methods


def test_scheduler_manager_contract_requires_scheduler_attribute() -> None:
    assert SCHEDULER_MANAGER_CONTRACT.required_attributes == (
        "scheduler",
    )


def test_other_default_contracts_have_no_required_attributes() -> None:
    assert TASK_REGISTRY_CONTRACT.required_attributes == ()
    assert JOB_STORE_CONTRACT.required_attributes == ()
    assert SCHEDULER_CONTRACT.required_attributes == ()


def test_contract_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        InterfaceContract(
            name=" ",
            required_methods=("execute",),
        )


def test_contract_rejects_duplicate_methods() -> None:
    with pytest.raises(ValueError):
        InterfaceContract(
            name="worker",
            required_methods=("execute", "execute"),
        )


def test_contract_rejects_duplicate_attributes() -> None:
    with pytest.raises(ValueError):
        InterfaceContract(
            name="worker",
            required_methods=(),
            required_attributes=("worker_id", "worker_id"),
        )


@pytest.mark.parametrize(
    "method_name",
    [
        "",
        " ",
    ],
)
def test_contract_rejects_invalid_method_names(
    method_name: str,
) -> None:
    with pytest.raises(ValueError):
        InterfaceContract(
            name="worker",
            required_methods=(method_name,),
        )


@pytest.mark.parametrize(
    "attribute_name",
    [
        "",
        " ",
    ],
)
def test_contract_rejects_invalid_attribute_names(
    attribute_name: str,
) -> None:
    with pytest.raises(ValueError):
        InterfaceContract(
            name="worker",
            required_methods=(),
            required_attributes=(attribute_name,),
        )


def test_get_contract_returns_expected_contracts() -> None:
    assert get_contract("scheduler_manager") is (
        SCHEDULER_MANAGER_CONTRACT
    )
    assert get_contract("task_registry") is TASK_REGISTRY_CONTRACT
    assert get_contract("job_store") is JOB_STORE_CONTRACT
    assert get_contract("scheduler") is SCHEDULER_CONTRACT


def test_get_contract_rejects_unknown_name() -> None:
    with pytest.raises(KeyError):
        get_contract("unknown_component")


@pytest.mark.parametrize(
    "invalid_name",
    [
        "",
        " ",
        None,
        123,
    ],
)
def test_get_contract_rejects_invalid_name(
    invalid_name: object,
) -> None:
    with pytest.raises(ValueError):
        get_contract(invalid_name)  # type: ignore[arg-type]


def test_get_all_contracts_returns_default_collection() -> None:
    contracts = get_all_contracts()

    assert contracts is DEFAULT_SCHEDULING_CONTRACTS
    assert len(contracts) == 4


def test_contracts_as_mapping_contains_all_contracts() -> None:
    mapping = contracts_as_mapping()

    assert set(mapping) == {
        "scheduler_manager",
        "task_registry",
        "job_store",
        "scheduler",
    }

    assert mapping["scheduler_manager"] is (
        SCHEDULER_MANAGER_CONTRACT
    )


def test_contracts_as_mapping_returns_independent_dictionary() -> None:
    first = contracts_as_mapping()
    second = contracts_as_mapping()

    assert first is not second

    first.clear()

    assert len(second) == 4
    assert len(get_all_contracts()) == 4


def test_contract_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        SCHEDULER_MANAGER_CONTRACT.name = "modified"  # type: ignore[misc]


def test_contract_method_collection_is_immutable() -> None:
    assert isinstance(
        SCHEDULER_MANAGER_CONTRACT.required_methods,
        tuple,
    )


def test_contract_descriptions_are_available() -> None:
    for contract in get_all_contracts():
        assert isinstance(contract.description, str)
        assert contract.description.strip()
