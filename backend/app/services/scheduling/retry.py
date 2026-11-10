"""Retry policies and execution handling for TeleForward scheduling."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from app.services.scheduling.base import (
    BaseScheduledTask,
    ScheduledTaskContext,
    ScheduledTaskResult,
    ScheduledTaskStatus,
)
from app.services.scheduling.executor import ScheduledTaskExecutor

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Configuration for retrying failed scheduled-task executions."""

    max_attempts: int = 3
    initial_delay_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 60.0
    jitter_fraction: float = 0.2

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be at least 1")

        if (
            isinstance(self.initial_delay_seconds, bool)
            or not isinstance(self.initial_delay_seconds, (int, float))
            or self.initial_delay_seconds < 0
        ):
            raise ValueError(
                "initial_delay_seconds cannot be negative"
            )

        if (
            isinstance(self.backoff_multiplier, bool)
            or not isinstance(self.backoff_multiplier, (int, float))
            or self.backoff_multiplier < 1
        ):
            raise ValueError(
                "backoff_multiplier must be at least 1"
            )

        if (
            isinstance(self.max_delay_seconds, bool)
            or not isinstance(self.max_delay_seconds, (int, float))
            or self.max_delay_seconds < 0
        ):
            raise ValueError(
                "max_delay_seconds cannot be negative"
            )

        if (
            isinstance(self.jitter_fraction, bool)
            or not isinstance(self.jitter_fraction, (int, float))
            or not 0 <= self.jitter_fraction <= 1
        ):
            raise ValueError(
                "jitter_fraction must be between 0 and 1"
            )

    def delay_for_attempt(
        self,
        attempt: int,
        *,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> float:
        """Calculate the delay before a retry.

        Attempt numbering starts at 1. The delay for attempt 1 is
        the initial delay.
        """

        if (
            isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt < 1
        ):
            raise ValueError("attempt must be a positive integer")

        delay = self.initial_delay_seconds * (
            self.backoff_multiplier ** (attempt - 1)
        )

        delay = min(delay, self.max_delay_seconds)

        if delay == 0 or self.jitter_fraction == 0:
            return float(delay)

        variation = delay * self.jitter_fraction

        return random_uniform(
            max(0.0, delay - variation),
            delay + variation,
        )


class RetryExecutor:
    """Execute scheduled tasks with a configurable retry policy.

    Each attempt uses the shared ScheduledTaskExecutor, preserving its
    concurrency controls and timeout behaviour.
    """

    def __init__(
        self,
        *,
        executor: ScheduledTaskExecutor,
        policy: RetryPolicy | None = None,
    ) -> None:
        if not isinstance(executor, ScheduledTaskExecutor):
            raise TypeError(
                "executor must be a ScheduledTaskExecutor"
            )

        if policy is not None and not isinstance(policy, RetryPolicy):
            raise TypeError("policy must be a RetryPolicy")

        self._executor = executor
        self._policy = policy or RetryPolicy()

    async def execute(
        self,
        task: BaseScheduledTask,
        context: ScheduledTaskContext,
        *,
        timeout_seconds: float | None = None,
        policy: RetryPolicy | None = None,
    ) -> ScheduledTaskResult:
        """Execute a task and retry failed results.

        Returns the final attempt's result. Attempt information is added
        to its metadata.
        """

        if not isinstance(task, BaseScheduledTask):
            raise TypeError("task must inherit from BaseScheduledTask")

        if not isinstance(context, ScheduledTaskContext):
            raise TypeError(
                "context must be a ScheduledTaskContext"
            )

        active_policy = policy or self._policy

        if not isinstance(active_policy, RetryPolicy):
            raise TypeError("policy must be a RetryPolicy")

        attempt_results: list[ScheduledTaskResult] = []

        for attempt in range(1, active_policy.max_attempts + 1):
            attempt_context = ScheduledTaskContext(
                job_id=context.job_id,
                execution_id=(
                    context.execution_id
                    if attempt == 1
                    else str(uuid4())
                ),
                scheduled_at=context.scheduled_at,
                started_at=datetime.now(timezone.utc),
                metadata={
                    **dict(context.metadata),
                    "attempt": attempt,
                    "max_attempts": active_policy.max_attempts,
                },
            )

            result = await self._executor.execute(
                task,
                attempt_context,
                timeout_seconds=timeout_seconds,
            )

            attempt_results.append(result)

            if result.status != ScheduledTaskStatus.FAILED:
                return self._build_final_result(
                    result,
                    attempt_results,
                )

            if attempt >= active_policy.max_attempts:
                break

            delay = active_policy.delay_for_attempt(attempt)

            logger.warning(
                "Scheduled task retry: task=%s job=%s "
                "attempt=%d/%d delay=%.2fs error=%s",
                task.name,
                context.job_id,
                attempt,
                active_policy.max_attempts,
                delay,
                result.error,
            )

            await asyncio.sleep(delay)

        final_result = attempt_results[-1]

        logger.error(
            "Scheduled task exhausted retries: task=%s job=%s "
            "attempts=%d",
            task.name,
            context.job_id,
            len(attempt_results),
        )

        return self._build_final_result(
            final_result,
            attempt_results,
        )

    @staticmethod
    def _build_final_result(
        result: ScheduledTaskResult,
        attempts: list[ScheduledTaskResult],
    ) -> ScheduledTaskResult:
        """Attach retry information to the final execution result."""

        metadata = {
            **dict(result.metadata),
            "attempt_count": len(attempts),
            "attempts": [
                {
                    "execution_id": attempt.execution_id,
                    "status": attempt.status.value,
                    "started_at": attempt.started_at.isoformat(),
                    "finished_at": attempt.finished_at.isoformat(),
                    "error": attempt.error,
                }
                for attempt in attempts
            ],
        }

        return ScheduledTaskResult(
            job_id=result.job_id,
            execution_id=result.execution_id,
            task_name=result.task_name,
            status=result.status,
            started_at=attempts[0].started_at,
            finished_at=max(
                attempt.finished_at for attempt in attempts
            ),
            message=result.message,
            error=result.error,
            metadata=metadata,
        )
