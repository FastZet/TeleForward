"""HTTP error handling for scheduling configuration APIs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.scheduling.configuration_access import (
    ConfigurationAccessDenied,
)
from app.services.scheduling.configuration_permissions import (
    ConfigurationPermissionError,
)
from app.services.scheduling.configuration_policy import (
    ConfigurationPolicyError,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConfigurationApiError:
    """Standard API error representation."""

    code: str
    message: str
    status_code: int
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
            },
        }

        if self.details is not None:
            result["error"]["details"] = self.details

        return result


def _response(
    error: ConfigurationApiError,
) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_dict(),
    )


async def handle_configuration_access_denied(
    request: Request,
    exc: ConfigurationAccessDenied,
) -> JSONResponse:
    logger.warning(
        "Configuration resource access denied: path=%s resource=%s",
        request.url.path,
        exc.result.resource_type.value,
    )

    return _response(
        ConfigurationApiError(
            code="CONFIGURATION_ACCESS_DENIED",
            message="Access to the requested configuration resource is denied",
            status_code=403,
            details={
                "resource_type": exc.result.resource_type.value,
                "resource_id": exc.result.resource_id,
            },
        )
    )


async def handle_configuration_permission_error(
    request: Request,
    exc: ConfigurationPermissionError,
) -> JSONResponse:
    logger.warning(
        "Configuration permission denied: path=%s",
        request.url.path,
    )

    return _response(
        ConfigurationApiError(
            code="CONFIGURATION_PERMISSION_DENIED",
            message="The required configuration permission is missing",
            status_code=403,
        )
    )


async def handle_configuration_policy_error(
    request: Request,
    exc: ConfigurationPolicyError,
) -> JSONResponse:
    result = getattr(exc, "result", None)

    details = None

    if result is not None and callable(
        getattr(result, "to_dict", None)
    ):
        details = result.to_dict()

    return _response(
        ConfigurationApiError(
            code="CONFIGURATION_POLICY_VIOLATION",
            message="The configuration violates an application policy",
            status_code=422,
            details=details,
        )
    )


async def handle_configuration_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = []

    for error in exc.errors():
        errors.append(
            {
                "location": [
                    str(part)
                    for part in error.get("loc", ())
                ],
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "validation_error"),
            }
        )

    return _response(
        ConfigurationApiError(
            code="CONFIGURATION_REQUEST_INVALID",
            message="The configuration request contains invalid data",
            status_code=422,
            details={"errors": errors},
        )
    )


async def handle_unexpected_configuration_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "Unexpected scheduling configuration API error: path=%s",
        request.url.path,
        exc_info=exc,
    )

    return _response(
        ConfigurationApiError(
            code="INTERNAL_CONFIGURATION_ERROR",
            message="An internal scheduling configuration error occurred",
            status_code=500,
        )
    )


def register_configuration_exception_handlers(
    app: FastAPI,
) -> None:
    """Register scheduling configuration exception handlers."""

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    app.add_exception_handler(
        ConfigurationAccessDenied,
        handle_configuration_access_denied,
    )

    app.add_exception_handler(
        ConfigurationPermissionError,
        handle_configuration_permission_error,
    )

    app.add_exception_handler(
        ConfigurationPolicyError,
        handle_configuration_policy_error,
    )

    app.add_exception_handler(
        RequestValidationError,
        handle_configuration_validation_error,
    )

    app.add_exception_handler(
        Exception,
        handle_unexpected_configuration_error,
    )
