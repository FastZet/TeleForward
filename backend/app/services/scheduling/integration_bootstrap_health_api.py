
"""HTTP API for scheduling bootstrap health."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.services.scheduling.integration_bootstrap_health import (
    BootstrapHealthReport,
    BootstrapHealthStatus,
)
from app.services.scheduling.integration_bootstrap_health_integration import (
    BootstrapHealthIntegrationError,
    get_bootstrap_health_report,
)


logger = logging.getLogger(__name__)

BOOTSTRAP_HEALTH_API_STATE_KEY = (
    "scheduling_bootstrap_health_api_router"
)

BOOTSTRAP_HEALTH_API_PATH = "/health/scheduler/bootstrap"


class BootstrapHealthAPIResponse(BaseModel):
    """Public response representation of bootstrap health."""

    model_config = ConfigDict(extra="forbid")

    status: BootstrapHealthStatus
    state: str
    context_available: bool
    components: dict[str, bool] = Field(default_factory=dict)
    validation_passed: bool
    cleanup_errors: list[str] = Field(default_factory=list)
    checked_at: str
    details: dict[str, Any] = Field(default_factory=dict)


def serialize_bootstrap_health_report(
    report: BootstrapHealthReport,
) -> BootstrapHealthAPIResponse:
    """Convert a domain health report into an API response."""
    if not isinstance(report, BootstrapHealthReport):
        raise TypeError(
            "report must be a BootstrapHealthReport"
        )

    return BootstrapHealthAPIResponse(
        status=report.status,
        state=report.state.value,
        context_available=report.context_available,
        components=dict(report.component_availability),
        validation_passed=report.validation_passed,
        cleanup_errors=list(report.cleanup_errors),
        checked_at=report.checked_at.isoformat(),
        details=dict(report.details),
    )


def _http_status_for_health(
    health_status: BootstrapHealthStatus,
) -> int:
    """Map health classifications to HTTP status codes."""
    if health_status is BootstrapHealthStatus.HEALTHY:
        return status.HTTP_200_OK

    if health_status is BootstrapHealthStatus.DEGRADED:
        return status.HTTP_200_OK

    if health_status is BootstrapHealthStatus.UNAVAILABLE:
        return status.HTTP_503_SERVICE_UNAVAILABLE

    if health_status is BootstrapHealthStatus.FAILED:
        return status.HTTP_503_SERVICE_UNAVAILABLE

    return status.HTTP_503_SERVICE_UNAVAILABLE


def create_bootstrap_health_router() -> APIRouter:
    """Create an independent router for bootstrap health."""

    router = APIRouter(tags=["Health"])

    @router.get(
        BOOTSTRAP_HEALTH_API_PATH,
        response_model=BootstrapHealthAPIResponse,
        summary="Scheduling bootstrap health",
        description=(
            "Returns the health status of the scheduling "
            "integration bootstrap."
        ),
    )
    async def get_scheduler_bootstrap_health() -> (
        BootstrapHealthAPIResponse
    ):
        try:
            report = get_bootstrap_health_report_from_app_context()
            response = serialize_bootstrap_health_report(report)

            return response

        except BootstrapHealthIntegrationError as exc:
            logger.warning(
                "Scheduling bootstrap health integration unavailable: %s",
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Scheduling bootstrap health is unavailable",
            ) from exc

        except Exception as exc:
            logger.exception(
                "Failed to retrieve scheduling bootstrap health"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to retrieve scheduling bootstrap health",
            ) from exc

    return router


def get_bootstrap_health_report_from_app_context() -> (
    BootstrapHealthReport
):
    """Resolve the health report from the active request context.

    This function is replaced by the request-aware endpoint dependency
    below when the router is created.
    """
    raise BootstrapHealthIntegrationError(
        "Request application context is not configured"
    )


def create_app_bootstrap_health_router() -> APIRouter:
    """Create a router whose endpoint resolves the current app state."""
    from fastapi import Request

    router = APIRouter(tags=["Health"])

    @router.get(
        BOOTSTRAP_HEALTH_API_PATH,
        response_model=BootstrapHealthAPIResponse,
        summary="Scheduling bootstrap health",
        description=(
            "Returns the health status of the scheduling "
            "integration bootstrap."
        ),
    )
    async def get_scheduler_bootstrap_health(
        request: Request,
    ) -> BootstrapHealthAPIResponse:
        try:
            report = get_bootstrap_health_report(request.app)
            response = serialize_bootstrap_health_report(report)

            response_status = _http_status_for_health(report.status)

            if response_status != status.HTTP_200_OK:
                raise HTTPException(
                    status_code=response_status,
                    detail=response.model_dump(mode="json"),
                )

            return response

        except BootstrapHealthIntegrationError as exc:
            logger.warning(
                "Scheduling bootstrap health integration unavailable: %s",
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Scheduling bootstrap health is unavailable",
            ) from exc

        except HTTPException:
            raise

        except Exception as exc:
            logger.exception(
                "Failed to retrieve scheduling bootstrap health"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to retrieve scheduling bootstrap health",
            ) from exc

    return router


def install_bootstrap_health_api(
    app: FastAPI,
    *,
    replace: bool = False,
) -> APIRouter:
    """Install the bootstrap health endpoint on a FastAPI app."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    existing = getattr(
        app.state,
        BOOTSTRAP_HEALTH_API_STATE_KEY,
        None,
    )

    if existing is not None:
        if not isinstance(existing, APIRouter):
            raise TypeError(
                "Existing bootstrap health API state is invalid"
            )

        if not replace:
            raise RuntimeError(
                "Bootstrap health API is already installed"
            )

        raise RuntimeError(
            "FastAPI routes cannot be safely replaced after registration"
        )

    router = create_app_bootstrap_health_router()
    app.include_router(router)

    setattr(
        app.state,
        BOOTSTRAP_HEALTH_API_STATE_KEY,
        router,
    )

    return router


def is_bootstrap_health_api_installed(app: FastAPI) -> bool:
    """Return whether the bootstrap health API is installed."""
    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    router = getattr(
        app.state,
        BOOTSTRAP_HEALTH_API_STATE_KEY,
        None,
    )

    if router is None:
        return False

    if not isinstance(router, APIRouter):
        raise TypeError(
            "Existing bootstrap health API state is invalid"
        )

    return True
