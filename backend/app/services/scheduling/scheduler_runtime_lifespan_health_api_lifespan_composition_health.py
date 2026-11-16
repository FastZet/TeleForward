
"""Health inspection for composed scheduler health API lifespans."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.scheduler_runtime_lifespan_health_api_lifespan_composition_integration import (
    get_scheduler_health_api_lifespan_composition_status,
)

logger = logging.getLogger(__name__)


class CompositionHealthStatus(StrEnum):
    """Health states for the lifespan composition."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CompositionHealthReport:
    """Immutable health inspection result."""

    status: CompositionHealthStatus
    installed: bool
    lifespan_valid: bool
    scheduler_lifespan_supplied: bool
    health_api_lifespan_supplied: bool
    application_lifespan_assigned: bool
    checked_at: datetime
    details: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate report fields."""

        if not isinstance(self.status, CompositionHealthStatus):
            raise TypeError(
                "status must be a CompositionHealthStatus"
            )

        boolean_fields = (
            self.installed,
            self.lifespan_valid,
            self.scheduler_lifespan_supplied,
            self.health_api_lifespan_supplied,
            self.application_lifespan_assigned,
        )

        if any(
            not isinstance(value, bool)
            for value in boolean_fields
        ):
            raise TypeError(
                "Health report state fields must be booleans"
            )

        if (
            not isinstance(self.checked_at, datetime)
            or self.checked_at.tzinfo is None
            or self.checked_at.utcoffset() is None
        ):
            raise ValueError(
                "checked_at must be timezone-aware"
            )

        if not isinstance(self.details, tuple):
            raise TypeError("details must be a tuple")

        if any(
            not isinstance(detail, str)
            for detail in self.details
        ):
            raise TypeError(
                "Every health detail must be a string"
            )

    @property
    def is_healthy(self) -> bool:
        """Return whether the composition is fully healthy."""

        return self.status is CompositionHealthStatus.HEALTHY

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return {
            "status": self.status.value,
            "installed": self.installed,
            "lifespan_valid": self.lifespan_valid,
            "scheduler_lifespan_supplied": (
                self.scheduler_lifespan_supplied
            ),
            "health_api_lifespan_supplied": (
                self.health_api_lifespan_supplied
            ),
            "application_lifespan_assigned": (
                self.application_lifespan_assigned
            ),
            "is_healthy": self.is_healthy,
            "checked_at": self.checked_at.isoformat(),
            "details": list(self.details),
        }


class SchedulerHealthAPILifespanCompositionHealthService:
    """Inspect the registration and readiness of a lifespan composition."""

    def __init__(
        self,
        app: FastAPI | None = None,
    ) -> None:
        if app is not None and not isinstance(app, FastAPI):
            raise TypeError("app must be a FastAPI instance or None")

        self._app = app

    @property
    def app(self) -> FastAPI | None:
        """Return the currently bound application."""

        return self._app

    def bind(self, app: FastAPI) -> None:
        """Bind the service to a FastAPI application."""

        if not isinstance(app, FastAPI):
            raise TypeError("app must be a FastAPI instance")

        self._app = app

    def inspect(
        self,
        app: FastAPI | None = None,
    ) -> CompositionHealthReport:
        """Inspect lifespan composition registration and readiness."""

        application = app or self._app

        if not isinstance(application, FastAPI):
            raise TypeError(
                "A FastAPI application must be supplied or bound"
            )

        checked_at = datetime.now(UTC)
        details: list[str] = []

        try:
            state = (
                get_scheduler_health_api_lifespan_composition_status(
                    application
                )
            )
        except Exception:
            logger.exception(
                "Unable to inspect scheduler health lifespan composition"
            )

            return CompositionHealthReport(
                status=CompositionHealthStatus.FAILED,
                installed=False,
                lifespan_valid=False,
                scheduler_lifespan_supplied=False,
                health_api_lifespan_supplied=False,
                application_lifespan_assigned=False,
                checked_at=checked_at,
                details=(
                    "Unable to inspect composition registration state",
                ),
            )

        installed = state["installed"]
        lifespan_valid = state["lifespan_valid"]
        scheduler_supplied = state[
            "scheduler_runtime_lifespan_supplied"
        ]
        health_api_supplied = state[
            "health_api_lifespan_supplied"
        ]

        integration_state = getattr(
            application.state,
            "scheduler_health_api_lifespan_composition",
            None,
        )

        registered_lifespan = (
            integration_state.get("lifespan")
            if isinstance(integration_state, dict)
            else None
        )

        application_lifespan_assigned = (
            callable(registered_lifespan)
            and application.router.lifespan_context
            is registered_lifespan
        )

        if not installed:
            details.append(
                "Lifespan composition is not registered"
            )

            return CompositionHealthReport(
                status=CompositionHealthStatus.UNAVAILABLE,
                installed=False,
                lifespan_valid=False,
                scheduler_lifespan_supplied=False,
                health_api_lifespan_supplied=False,
                application_lifespan_assigned=False,
                checked_at=checked_at,
                details=tuple(details),
            )

        if not lifespan_valid:
            details.append(
                "Registered lifespan factory is invalid"
            )

        if not scheduler_supplied:
            details.append(
                "Scheduler runtime lifespan was not supplied"
            )

        if not health_api_supplied:
            details.append(
                "Scheduler health API lifespan was not supplied"
            )

        if not application_lifespan_assigned:
            details.append(
                "Composed lifespan is not assigned to the FastAPI router"
            )

        if not lifespan_valid:
            health_status = CompositionHealthStatus.FAILED
        elif not application_lifespan_assigned:
            health_status = CompositionHealthStatus.DEGRADED
        elif not scheduler_supplied or not health_api_supplied:
            health_status = CompositionHealthStatus.DEGRADED
        else:
            health_status = CompositionHealthStatus.HEALTHY

        return CompositionHealthReport(
            status=health_status,
            installed=installed,
            lifespan_valid=lifespan_valid,
            scheduler_lifespan_supplied=scheduler_supplied,
            health_api_lifespan_supplied=health_api_supplied,
            application_lifespan_assigned=(
                application_lifespan_assigned
            ),
            checked_at=checked_at,
            details=tuple(details),
        )

    def is_healthy(
        self,
        app: FastAPI | None = None,
    ) -> bool:
        """Return whether the composition passes all readiness checks."""

        return self.inspect(app).is_healthy

    def get_status(
        self,
        app: FastAPI | None = None,
    ) -> CompositionHealthStatus:
        """Return the current composition health status."""

        return self.inspect(app).status
