"""Apply scheduled-job configuration reconciliation plans."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.scheduling.configuration_sync import (
    ConfigurationSyncPlan,
)
from app.services.scheduling.task_config import ScheduledTaskConfig


CreateCallback = Callable[
    [ScheduledTaskConfig],
    Awaitable[None] | None,
]

UpdateCallback = Callable[
    [ScheduledTaskConfig],
    Awaitable[None] | None,
]

DeleteCallback = Callable[
    [str],
    Awaitable[None] | None,
]


@dataclass(frozen=True, slots=True)
class ConfigurationApplyFailure:
    """Details of an individual reconciliation failure."""

    operation: str
    target: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class ConfigurationApplyResult:
    """Summary of a configuration reconciliation operation."""

    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    failures: tuple[ConfigurationApplyFailure, ...] = ()

    @property
    def success(self) -> bool:
        return not self.failures

    @property
    def changed_count(self) -> int:
        return (
            len(self.created)
            + len(self.updated)
            + len(self.deleted)
        )

    @property
    def failure_count(self) -> int:
        return len(self.failures)


@dataclass(slots=True)
class _ApplyState:
    """Mutable state used internally during reconciliation."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    failures: list[ConfigurationApplyFailure] = field(
        default_factory=list
    )


class ConfigurationApplier:
    """Apply configuration reconciliation plans sequentially."""

    def __init__(
        self,
        *,
        create_callback: CreateCallback,
        update_callback: UpdateCallback,
        delete_callback: DeleteCallback,
    ) -> None:
        for name, callback in (
            ("create_callback", create_callback),
            ("update_callback", update_callback),
            ("delete_callback", delete_callback),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")

        self._create_callback = create_callback
        self._update_callback = update_callback
        self._delete_callback = delete_callback

    async def apply(
        self,
        plan: ConfigurationSyncPlan,
    ) -> ConfigurationApplyResult:
        """Apply all operations in a reconciliation plan.

        Operations are processed in this order:
        1. Create missing jobs.
        2. Update changed jobs.
        3. Delete jobs no longer present.

        Failures are recorded individually. Processing continues so that
        independent operations can still succeed.
        """

        if not isinstance(plan, ConfigurationSyncPlan):
            raise TypeError(
                "plan must be a ConfigurationSyncPlan instance"
            )

        state = _ApplyState()

        await self._apply_creations(plan, state)
        await self._apply_updates(plan, state)
        await self._apply_deletions(plan, state)

        return ConfigurationApplyResult(
            created=tuple(state.created),
            updated=tuple(state.updated),
            deleted=tuple(state.deleted),
            failures=tuple(state.failures),
        )

    async def _apply_creations(
        self,
        plan: ConfigurationSyncPlan,
        state: _ApplyState,
    ) -> None:
        for config in plan.to_create:
            await self._execute(
                operation="create",
                target=config.task_name,
                callback=self._create_callback,
                argument=config,
                successful_targets=state.created,
                state=state,
            )

    async def _apply_updates(
        self,
        plan: ConfigurationSyncPlan,
        state: _ApplyState,
    ) -> None:
        for config in plan.to_update:
            await self._execute(
                operation="update",
                target=config.task_name,
                callback=self._update_callback,
                argument=config,
                successful_targets=state.updated,
                state=state,
            )

    async def _apply_deletions(
        self,
        plan: ConfigurationSyncPlan,
        state: _ApplyState,
    ) -> None:
        for job_id in plan.to_delete:
            await self._execute(
                operation="delete",
                target=job_id,
                callback=self._delete_callback,
                argument=job_id,
                successful_targets=state.deleted,
                state=state,
            )

    @staticmethod
    async def _execute(
        *,
        operation: str,
        target: str,
        callback: Callable[[Any], Any],
        argument: Any,
        successful_targets: list[str],
        state: _ApplyState,
    ) -> None:
        """Execute one operation and record its outcome."""

        try:
            result = callback(argument)

            if inspect.isawaitable(result):
                await result

            successful_targets.append(target)

        except Exception as exc:
            state.failures.append(
                ConfigurationApplyFailure(
                    operation=operation,
                    target=target,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            )
