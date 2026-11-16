
"""Health reporting for scheduling integration bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.services.scheduling.integration_bootstrap import (
    BootstrapState,
    SchedulingIntegrationBootstrap,
)


class BootstrapHealthStatus(StrEnum):
    """Overall health classification of the bootstrap."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BootstrapHealthReport:
    """Immutable health snapshot for scheduling bootstrap."""

    status: BootstrapHealthStatus
    bootstrap_state: BootstrapState
    context_available: bool
    required_components_available: bool
    available_components: tuple[str, ...]
    missing_components: tuple[str, ...]
    validation_passed: bool | None
    cleanup_failures: tuple[str, ...]
    checked_at: datetime
    details: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.checked_at.tzinfo is None:
            raise ValueError("checked_at must be timezone-aware")

        if self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must have a UTC offset")

        if not isinstance(self.available_components, tuple):
            raise TypeError("available_components must be a tuple")

        if not isinstance(self.missing_components, tuple):
            raise TypeError("missing_components must be a tuple")

        if not isinstance(self.cleanup_failures, tuple):
            raise TypeError("cleanup_failures must be a tuple")

        if not isinstance(self.details, tuple):
            raise TypeError("details must be a tuple")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible health representation."""
        return {
            "status": self.status.value,
            "bootstrap_state": self.bootstrap_state.value,
            "context_available": self.context_available,
            "required_components_available": (
                self.required_components_available
            ),
            "available_components": list(self.available_components),
            "missing_components": list(self.missing_components),
            "validation_passed": self.validation_passed,
            "cleanup_failures": list(self.cleanup_failures),
            "checked_at": self.checked_at.isoformat(),
            "details": list(self.details),
        }


class SchedulingBootstrapHealthService:
    """Inspect and classify scheduling bootstrap health."""

    REQUIRED_COMPONENTS = (
        "scheduler_manager",
        "task_registry",
        "job_store",
    )

    def __init__(
        self,
        bootstrap: SchedulingIntegrationBootstrap | None = None,
    ) -> None:
        self._bootstrap = bootstrap

    @property
    def bootstrap(self) -> SchedulingIntegrationBootstrap:
        if self._bootstrap is None:
            raise RuntimeError(
                "Scheduling bootstrap health service is not bound"
            )

        return self._bootstrap

    def bind(
        self,
        bootstrap: SchedulingIntegrationBootstrap,
    ) -> None:
        """Bind the service to a bootstrap instance."""
        if not isinstance(
            bootstrap,
            SchedulingIntegrationBootstrap,
        ):
            raise TypeError(
                "bootstrap must be a SchedulingIntegrationBootstrap"
            )

        self._bootstrap = bootstrap

    @staticmethod
    def _extract_cleanup_failures(
        error: str | None,
    ) -> tuple[str, ...]:
        """Extract cleanup failure details from the bootstrap report."""
        if not error or "cleanup failures: " not in error:
            return ()

        _, separator, remainder = error.partition(
            "cleanup failures: "
        )

        if not separator:
            return ()

        return tuple(
            item.strip()
            for item in remainder.split(";")
            if item.strip()
        )

    @staticmethod
    def _get_validation_result(
        bootstrap: SchedulingIntegrationBootstrap,
    ) -> bool | None:
        report = bootstrap.report

        if report is None or report.validation_report is None:
            return None

        return report.validation_report.valid

    def inspect(self) -> BootstrapHealthReport:
        """Inspect bootstrap state and return a health snapshot."""
        bootstrap = self._bootstrap

        if bootstrap is None:
            return BootstrapHealthReport(
                status=BootstrapHealthStatus.UNAVAILABLE,
                bootstrap_state=BootstrapState.NOT_STARTED,
                context_available=False,
                required_components_available=False,
                available_components=(),
                missing_components=self.REQUIRED_COMPONENTS,
                validation_passed=None,
                cleanup_failures=(),
                checked_at=datetime.now(UTC),
                details=("Bootstrap health service is not bound",),
            )

        state = bootstrap.state
        components = bootstrap.components
        report = bootstrap.report

        available = tuple(
            name
            for name in self.REQUIRED_COMPONENTS
            if name in components
        )

        missing = tuple(
            name
            for name in self.REQUIRED_COMPONENTS
            if name not in components
        )

        required_available = not missing

        context_available = False

        if state is BootstrapState.READY:
            try:
                context_available = bootstrap.context.is_validated
            except Exception:
                context_available = False

        validation_passed = self._get_validation_result(bootstrap)

        cleanup_failures = self._extract_cleanup_failures(
            report.error if report else None
        )

        details: list[str] = []

        if state is BootstrapState.NOT_STARTED:
            status = BootstrapHealthStatus.UNAVAILABLE
            details.append("Bootstrap has not been started")

        elif state is BootstrapState.INITIALISING:
            status = BootstrapHealthStatus.DEGRADED
            details.append("Bootstrap is currently initialising")

        elif state is BootstrapState.CLOSED:
            status = BootstrapHealthStatus.UNAVAILABLE
            details.append("Bootstrap has been closed")

        elif state is BootstrapState.FAILED:
            status = BootstrapHealthStatus.FAILED
            details.append("Bootstrap has failed")

        elif state is BootstrapState.READY:
            if (
                context_available
                and required_available
                and validation_passed is True
                and not cleanup_failures
            ):
                status = BootstrapHealthStatus.HEALTHY
                details.append(
                    "Bootstrap and integration validation are healthy"
                )
            else:
                status = BootstrapHealthStatus.DEGRADED
                details.append(
                    "Bootstrap is ready but one or more health checks "
                    "did not pass"
                )

        else:
            status = BootstrapHealthStatus.FAILED
            details.append("Unrecognised bootstrap lifecycle state")

        if missing:
            details.append(
                "Missing required components: "
                + ", ".join(missing)
            )

        if validation_passed is False:
            details.append("Integration validation did not pass")

        if validation_passed is None and state is BootstrapState.READY:
            details.append(
                "Integration validation result is unavailable"
            )

        if not context_available and state is BootstrapState.READY:
            details.append(
                "Validated integration context is unavailable"
            )

        if cleanup_failures:
            details.append(
                "Cleanup failures were recorded"
            )

        if report is not None and report.error:
            details.append(
                "Bootstrap error: " + report.error
            )

        return BootstrapHealthReport(
            status=status,
            bootstrap_state=state,
            context_available=context_available,
            required_components_available=required_available,
            available_components=available,
            missing_components=missing,
            validation_passed=validation_passed,
            cleanup_failures=cleanup_failures,
            checked_at=datetime.now(UTC),
            details=tuple(details),
        )

    def get_status(self) -> BootstrapHealthStatus:
        """Return the current overall health classification."""
        return self.inspect().status

    def is_healthy(self) -> bool:
        """Return True only when bootstrap health is fully healthy."""
        return self.get_status() is BootstrapHealthStatus.HEALTHY
