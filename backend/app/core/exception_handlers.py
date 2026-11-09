
"""
TeleForward global exception handlers.

Provides consistent HTTP error responses, application exception
mapping, request validation handling, and safe unexpected error
handling.
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import TeleForwardError
from app.core.responses import error_response


logger = logging.getLogger(__name__)


APPLICATION_EXCEPTION_STATUS_CODES: dict[str, int] = {
    "ConfigurationError": 500,
    "DatabaseError": 503,
    "StorageError": 503,
    "AuthenticationError": 401,
    "AuthorizationError": 403,
    "SessionError": 401,
    "ValidationError": 422,
    "NotFoundError": 404,
    "ConflictError": 409,
    "RateLimitError": 429,
    "TelegramError": 502,
    "TelegramFloodWaitError": 429,
    "TelegramAccountError": 400,
    "ForwardingError": 422,
    "FilterError": 422,
    "TransformationError": 422,
    "DuplicateMessageError": 409,
    "SchedulingError": 422,
    "WorkerError": 503,
    "QueueError": 503,
    "BackupError": 500,
    "RestoreError": 500,
}


def _request_metadata(request: Request) -> dict[str, Any]:
    """Return safe request metadata for structured logging."""
    return {
        "method": request.method,
        "path": request.url.path,
        "request_id": getattr(
            request.state,
            "request_id",
            None,
        ),
    }


def _error_code_from_status(status_code: int) -> str:
    """Convert an HTTP status code into a stable error identifier."""
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = "HTTP Error"

    return (
        phrase.upper()
        .replace(" ", "_")
        .replace("-", "_")
    )


async def application_exception_handler(
    request: Request,
    exc: TeleForwardError,
) -> JSONResponse:
    """Handle TeleForward application exceptions."""
    exception_name = type(exc).__name__

    status_code = APPLICATION_EXCEPTION_STATUS_CODES.get(
        exception_name,
        500,
    )

    if status_code >= 500:
        logger.error(
            "Application exception",
            extra={
                **_request_metadata(request),
                "exception_type": exception_name,
            },
            exc_info=exc,
        )
    else:
        logger.warning(
            "Application exception",
            extra={
                **_request_metadata(request),
                "exception_type": exception_name,
            },
        )

    message = (
        str(exc)
        if status_code < 500
        else "An internal application error occurred."
    )

    return JSONResponse(
        status_code=status_code,
        content=error_response(
            code=exception_name.upper(),
            message=message,
        ).model_dump(mode="json"),
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Handle HTTP exceptions using the standard error envelope."""
    detail = exc.detail

    if isinstance(detail, dict):
        code = str(
            detail.get("code")
            or _error_code_from_status(exc.status_code)
        )

        message = str(
            detail.get("message")
            or "The request could not be completed."
        )

        details = detail.get("details")

    else:
        code = _error_code_from_status(exc.status_code)
        message = (
            str(detail)
            if isinstance(detail, str)
            else "The request could not be completed."
        )
        details = None

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            code=code,
            message=message,
            details=details,
        ).model_dump(mode="json"),
        headers=exc.headers,
    )


async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """
    Handle request validation failures.

    Sensitive input values are deliberately excluded from
    the response.
    """
    validation_errors = []

    for error in exc.errors():
        validation_errors.append({
            "location": [
                str(part)
                for part in error.get("loc", ())
            ],
            "message": error.get("msg", "Invalid input."),
            "type": error.get("type", "validation_error"),
        })

    logger.warning(
        "Request validation failed",
        extra={
            **_request_metadata(request),
            "validation_error_count": len(validation_errors),
        },
    )

    return JSONResponse(
        status_code=422,
        content=error_response(
            code="REQUEST_VALIDATION_FAILED",
            message="One or more request fields are invalid.",
            details=validation_errors,
        ).model_dump(mode="json"),
    )


async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle unexpected exceptions without exposing internals."""
    logger.exception(
        "Unhandled application exception",
        extra=_request_metadata(request),
    )

    return JSONResponse(
        status_code=500,
        content=error_response(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal error occurred.",
        ).model_dump(mode="json"),
    )


def register_exception_handlers(
    application: FastAPI,
) -> None:
    """Register all global application exception handlers."""
    application.add_exception_handler(
        TeleForwardError,
        application_exception_handler,
    )

    application.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )

    application.add_exception_handler(
        RequestValidationError,
        request_validation_exception_handler,
    )

    application.add_exception_handler(
        Exception,
        unexpected_exception_handler,
    )

    logger.debug("Global exception handlers registered")
