
"""
TeleForward health and availability schemas.

Defines:
- Overall application health.
- Individual component health.
- Readiness and liveness responses.
- Dependency diagnostics.

Health responses must not expose credentials, connection strings,
session tokens, or other sensitive configuration.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import ResponseSchema


class HealthStatus(StrEnum):
    """Overall health state."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentStatus(StrEnum):
    """Health state of an individual component."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthComponentResponse(ResponseSchema):
    """Sanitised health information for one application component."""

    name: str = Field(
        min_length=1,
        max_length=100,
    )

    status: ComponentStatus

    message: str | None = Field(
        default=None,
        max_length=500,
    )

    checked_at: datetime

    response_time_ms: float | None = Field(
        default=None,
        ge=0,
    )


class ApplicationHealthResponse(ResponseSchema):
    """Detailed application health response."""

    status: HealthStatus

    application: str = Field(
        min_length=1,
        max_length=100,
    )

    version: str = Field(
        min_length=1,
        max_length=50,
    )

    uptime_seconds: float = Field(
        ge=0,
    )

    checked_at: datetime

    components: list[HealthComponentResponse] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_component_statuses(self):
        """Prevent an inconsistent overall health status."""

        component_statuses = {
            component.status
            for component in self.components
        }

        if (
            ComponentStatus.UNHEALTHY in component_statuses
            and self.status == HealthStatus.HEALTHY
        ):
            raise ValueError(
                "Overall status cannot be healthy when a component is unhealthy"
            )

        if (
            ComponentStatus.DEGRADED in component_statuses
            and self.status == HealthStatus.HEALTHY
        ):
            raise ValueError(
                "Overall status cannot be healthy when a component is degraded"
            )

        return self


class LivenessResponse(ResponseSchema):
    """Liveness probe response.

    Indicates whether the application process is running.
    It should not depend on external service availability.
    """

    status: str = Field(
        default="alive",
        pattern=r"^alive$",
    )

    checked_at: datetime


class ReadinessResponse(ResponseSchema):
    """Readiness probe response.

    Indicates whether the application can accept normal requests.
    """

    ready: bool

    status: HealthStatus

    checked_at: datetime

    unavailable_components: list[str] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_readiness(self):
        """Ensure readiness and health status are consistent."""

        if self.ready and self.status == HealthStatus.UNHEALTHY:
            raise ValueError(
                "An unhealthy application cannot be ready"
            )

        if self.ready and self.unavailable_components:
            raise ValueError(
                "A ready application cannot report unavailable components"
            )

        if not self.ready and self.status == HealthStatus.HEALTHY:
            raise ValueError(
                "A healthy application cannot be marked as not ready"
            )

        return self


class DependencyHealthResponse(ResponseSchema):
    """Sanitised status of an external or internal dependency."""

    name: str = Field(
        min_length=1,
        max_length=100,
    )

    status: ComponentStatus

    required: bool = True

    response_time_ms: float | None = Field(
        default=None,
        ge=0,
    )

    checked_at: datetime

    message: str | None = Field(
        default=None,
        max_length=500,
    )
