
"""HTTP API for scheduler runtime lifespan health."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.services.scheduling.scheduler_runtime_lifespan_health import (
    SchedulerLifespanHealthStatus,
)
from app.services.scheduling.scheduler_runtime_lifespan_health_integration import (
    SchedulerLifespanHealthIntegrationError,
    get_scheduler_lifespan_health_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


def _http_status_for_health(
    health_status: str,
) -> int:
    """Translate scheduler health into an HTTP status code."""

    if health_status == SchedulerLifespanHealthStatus.HEALTHY.value:
        return status.HTTP_200_OK

    if health_status == SchedulerLifespanHealthStatus.DEGRADED.value:
        return status.HTTP_503_SERVICE_UNAVAILABLE

    if health_status == SchedulerLifespanHealthStatus.UNAVAILABLE.value:
        return status.HTTP_503_SERVICE_UNAVAILABLE

    if health_status == SchedulerLifespanHealthStatus.FAILED.value:
        return status.HTTP_503_SERVICE_UNAVAILABLE

    return status.HTTP_503_SERVICE_UNAVAILABLE


def _build_health_response(
    report: dict[str, Any],
) -> JSONResponse:
    """Build an HTTP response from a scheduler health report."""

    health_status = report.get("status")

    if not isinstance(health_status, str):
        raise ValueError(
            "Health report must contain a string status"
        )

    return JSONResponse(
        status_code=_http_status_for_health(health_status),
        content=report,
    )


@router.get(
    "/scheduler",
    summary="Scheduler runtime health",
    description=(
        "Returns scheduler runtime lifecycle health and diagnostic "
        "information. Returns HTTP 200 only when the scheduler is healthy."
    ),
    response_class=JSONResponse,
)
async def scheduler_runtime_health(
    request: Request,
) -> JSONResponse:
    """Return the scheduler runtime health report."""

    try:
        report = get_scheduler_lifespan_health_status(
            request.app
        )

        return _build_health_response(report)

    except SchedulerLifespanHealthIntegrationError as exc:
        logger.exception(
            "Scheduler lifespan health integration is unavailable"
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler health service is unavailable",
        ) from exc

    except ValueError as exc:
        logger.exception(
            "Scheduler lifespan health report is invalid"
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler health report is invalid",
        ) from exc

    except Exception as exc:
        logger.exception(
            "Unexpected scheduler health API failure"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to inspect scheduler health",
        ) from exc


def create_scheduler_health_router() -> APIRouter:
    """Return the scheduler health API router."""

    return router


def install_scheduler_health_api(
    app: FastAPI,
    *,
    replace: bool = False,
) -> APIRouter:
    """
    Include the scheduler health router in a FastAPI application.

    The scheduler health service must be installed separately.

    Calling this function repeatedly is rejected unless replace=True.
    """

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    if not isinstance(replace, bool):
        raise TypeError("replace must be a boolean")

    state_key = "scheduler_health_api_installed"

    already_installed = getattr(
        app.state,
        state_key,
        False,
    )

    if already_installed and not replace:
        raise RuntimeError(
            "Scheduler health API is already installed"
        )

    if already_installed and replace:
        logger.warning(
            "Scheduler health API is already registered; "
            "FastAPI routes cannot be safely removed and replaced"
        )
        return router

    app.include_router(router)

    setattr(app.state, state_key, True)

    logger.info("Scheduler health API installed")

    return router
