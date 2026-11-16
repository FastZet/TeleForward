
"""Cancellation-aware cleanup primitives for scheduler health lifespans.

This module separates cancellation from ordinary cleanup failures.

Policy:
- Every cleanup operation is attempted.
- Cancellation is never hidden inside a BaseExceptionGroup.
- Ordinary cleanup failures are retained and reported.
- If cancellation occurs, it takes precedence over ordinary cleanup errors.
- Repeated external cancellation does not interrupt the cleanup task.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)

CleanupCallback = Callable[[], Any | Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class CleanupFailure:
    """A failure raised by an individual cleanup operation."""

    operation: str
    error: Exception

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ValueError("operation must be a non-empty string")

        if not isinstance(self.error, Exception):
            raise TypeError("error must be an Exception instance")


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """Immutable result of a cleanup sequence."""

    failures: tuple[CleanupFailure, ...]
    cancellation: asyncio.CancelledError | None
    cancellation_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.failures, tuple):
            raise TypeError("failures must be a tuple")

        if any(not isinstance(item, CleanupFailure) for item in self.failures):
            raise TypeError("failures must contain CleanupFailure instances")

        if self.cancellation is not None and not isinstance(
            self.cancellation,
            asyncio.CancelledError,
        ):
            raise TypeError("cancellation must be CancelledError or None")

        if (
            isinstance(self.cancellation_count, bool)
            or not isinstance(self.cancellation_count, int)
            or self.cancellation_count < 0
        ):
            raise ValueError("cancellation_count must be a non-negative integer")

    @property
    def succeeded(self) -> bool:
        return not self.failures and self.cancellation is None

    @property
    def has_failures(self) -> bool:
        return bool(self.failures)


class CleanupExecutionError(RuntimeError):
    """Raised when cleanup fails without cancellation."""

    def __init__(self, report: CleanupReport) -> None:
        if not isinstance(report, CleanupReport):
            raise TypeError("report must be a CleanupReport")

        if not report.failures:
            raise ValueError("report must contain at least one failure")

        if report.cancellation is not None:
            raise ValueError(
                "CleanupExecutionError cannot represent cancellation"
            )

        self.report = report

        details = "; ".join(
            f"{failure.operation}: {failure.error}"
            for failure in report.failures
        )

        super().__init__(f"One or more cleanup operations failed: {details}")


class CleanupCancelledError(asyncio.CancelledError):
    """Cancellation raised after cleanup, with ordinary failures attached."""

    def __init__(self, report: CleanupReport) -> None:
        if not isinstance(report, CleanupReport):
            raise TypeError("report must be a CleanupReport")

        if report.cancellation is None:
            raise ValueError("report must contain cancellation")

        self.report = report

        super().__init__(
            f"Cleanup was cancelled after "
            f"{report.cancellation_count} cancellation request(s)"
        )


async def _invoke(callback: CleanupCallback) -> None:
    """Invoke a synchronous or asynchronous cleanup callback."""

    result = callback()

    if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
        await result


async def execute_cleanup_sequence(
    operations: Sequence[tuple[str, CleanupCallback]],
) -> CleanupReport:
    """Execute every cleanup operation and collect its failures.

    CancelledError raised by an individual cleanup callback is recorded
    separately. It does not prevent subsequent cleanup operations.
    """

    if isinstance(operations, (str, bytes)):
        raise TypeError("operations must be a sequence of operation pairs")

    failures: list[CleanupFailure] = []
    cancellation: asyncio.CancelledError | None = None
    cancellation_count = 0

    for operation in operations:
        if (
            not isinstance(operation, tuple)
            or len(operation) != 2
        ):
            raise TypeError(
                "each operation must be a (name, callback) tuple"
            )

        name, callback = operation

        if not isinstance(name, str) or not name.strip():
            raise ValueError("operation name must be non-empty")

        if not callable(callback):
            raise TypeError(f"callback for {name!r} must be callable")

        try:
            await _invoke(callback)

        except asyncio.CancelledError as exc:
            cancellation_count += 1

            if cancellation is None:
                cancellation = exc

            logger.warning(
                "Cleanup operation %s raised cancellation",
                name,
                exc_info=True,
            )

        except Exception as exc:
            failures.append(
                CleanupFailure(
                    operation=name,
                    error=exc,
                )
            )

            logger.exception(
                "Cleanup operation %s failed",
                name,
            )

    return CleanupReport(
        failures=tuple(failures),
        cancellation=cancellation,
        cancellation_count=cancellation_count,
    )


async def execute_cleanup_resiliently(
    operations: Sequence[tuple[str, CleanupCallback]],
) -> CleanupReport:
    """Run cleanup in a shielded task.

    External cancellation requests are deferred until the cleanup task
    finishes. The returned report distinguishes callback cancellation
    from cancellation of the task awaiting cleanup.
    """

    cleanup_task = asyncio.create_task(
        execute_cleanup_sequence(operations),
        name="scheduler-lifespan-cleanup",
    )

    deferred_cancellations = 0
    external_cancellation: asyncio.CancelledError | None = None

    while True:
        try:
            report = await asyncio.shield(cleanup_task)
            break

        except asyncio.CancelledError as exc:
            if cleanup_task.done():
                # The cleanup task itself completed by raising cancellation.
                try:
                    report = cleanup_task.result()
                except asyncio.CancelledError as cleanup_exc:
                    report = CleanupReport(
                        failures=(),
                        cancellation=cleanup_exc,
                        cancellation_count=1,
                    )
                break

            deferred_cancellations += 1

            if external_cancellation is None:
                external_cancellation = exc

            logger.warning(
                "External cancellation deferred while lifespan cleanup "
                "continues"
            )

    if external_cancellation is not None:
        cancellation_count = (
            report.cancellation_count + deferred_cancellations
        )

        return CleanupReport(
            failures=report.failures,
            cancellation=external_cancellation,
            cancellation_count=cancellation_count,
        )

    return report


def raise_for_cleanup_report(report: CleanupReport) -> None:
    """Raise according to cleanup policy.

    Cancellation takes precedence over ordinary failures. Ordinary
    failures remain available through the cancellation exception's report.
    """

    if not isinstance(report, CleanupReport):
        raise TypeError("report must be a CleanupReport")

    if report.cancellation is not None:
        raise CleanupCancelledError(report) from report.cancellation

    if report.failures:
        error = CleanupExecutionError(report)

        if len(report.failures) == 1:
            raise error from report.failures[0].error

        raise error from ExceptionGroup(
            "Cleanup operation failures",
            [failure.error for failure in report.failures],
        )


async def run_cleanup(
    operations: Sequence[tuple[str, CleanupCallback]],
) -> CleanupReport:
    """Run cleanup and apply the cancellation-priority policy."""

    report = await execute_cleanup_resiliently(operations)
    raise_for_cleanup_report(report)
    return report
