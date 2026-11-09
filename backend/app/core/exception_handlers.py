
"""
TeleForward centralised exception handlers.

Converts application exceptions, HTTP errors, validation failures
and unexpected exceptions into consistent API error responses.
"""

from collections.abc import Callable

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    DatabaseError,
    DuplicateMessageError,
    ForwardingError,
    RateLimitExceededError,
    ResourceConflictError,
    ResourceNotFoundError,
    RestoreError,
    SchedulingError,
    StorageError,
    TeleForwardError,
    TelegramError,
    ValidationError,
)
from app.core.responses import error_response


logger = structlog.get_logger(__name__)


# ============================================================
# Exception-to-HTTP status mapping
# ============================================================

EXCEPTION_STATUS_CODES: dict[type[Exception], int] = {
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    AuthorizationError: status.HTTP_403_FORBIDDEN,
    ValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ResourceNotFoundError: status.HTTP_404_NOT_FOUND,
    ResourceConflictError: status.HTTP_409_CONFLICT,
    DuplicateMessageError: status.HTTP_409_CONFLICT,
    RateLimitExceededError: status.HTTP_429_TOO_MANY_REQUESTS,
    ConfigurationError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    DatabaseError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    StorageError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ForwardingError: status.HTTP_502_BAD_GATEWAY,
    TelegramError: status.HTTP_502_BAD_GATEWAY,
    SchedulingError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    RestoreError: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


def get_exception_status_code(
    exception: TeleForwardError,
) -> int:
    """Resolve the HTTP status code for an application exception."""
    for exception_type in type(exception).__mro__:
        if exception_type in EXCEPTION_STATUS_CODES:
            return EXCEPTION_STATUS_CODES[exception_type]

    return status.HTTP_500_INTERNAL_SERVER_ERROR


def get_request_id(request: Request) -> str | None:
    """Retrieve the request correlation ID, if available."""
    return getattr(request.state, "request_id", None)


def create_error_response(
    *,
    message: str,
    error_code: str,
    status_code: int,
    request_id: str | None = None,
    details: dict | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a consistent JSON error response."""
    response_details = details or {}

    if request_id:
        response_details["request_id"] = request_id

    return JSONResponse(
        status_code=status_code,
        content=error_response(
            message=message,
            error_code=error_code,
            details=response_details,
        ).model_dump(mode="json"),
        headers=headers,
    )


# ============================================================
# Application exception handler
# ============================================================

async def teleforward_exception_handler(
    request: Request,
    exception: TeleForwardError,
) -> JSONResponse:
    """Handle exceptions raised by TeleForward application services."""
    status_code = get_exception_status_code(exception)
    request_id = get_request_id(request)

    if status_code >= 500:
        logger.error(
            "application_exception",
            exception_type=type(exception).__name__,
            message=exception.message,
            request_id=request_id,
            path=request.url.path,
        )
    else:
        logger.warning(
            "application_exception",
            exception_type=type(exception).__name__,
            message=exception.message,
            request_id=request_id,
            path=request.url.path,
        )

    # Internal exception details are deliberately not exposed
    # to clients. Future endpoints can provide explicitly
    # sanitised, user-facing details where appropriate.
    return create_error_response(
        message=(
            exception.message
            if status_code < 500
            else "An internal application error occurred."
        ),
        error_code=type(exception).__name__.upper(),
        status_code=status_code,
        request_id=request_id,
    )


# ============================================================
# HTTP exception handler
# ============================================================

async def http_exception_handler(
    request: Request,
    exception: StarletteHTTPException,
) -> JSONResponse:
    """Convert framework HTTP exceptions into standard responses."""
    detail = exception.detail

    message = (
        detail
        if isinstance(detail, str)
        else "The request could not be completed."
    )

    return create_error_response(
        message=message,
        error_code=f"HTTP_{exception.status_code}",
        status_code=exception.status_code,
        request_id=get_request_id(request),
        headers=exception.headers,
    )


# ============================================================
# Request validation handler
# ============================================================

async def request_validation_exception_handler(
    request: Request,
    exception: RequestValidationError,
) -> JSONResponse:
    """
    Handle invalid request payloads and parameters.

    Only validation locations, messages and error types are
    returned. Submitted values are never included in responses.
    """
    validation_errors = [
        {
            "location": list(error.get("loc", ())),
            "message": error.get("msg", "Invalid value."),
            "type": error.get("type", "validation_error"),
        }
        for error in exception.errors()
    ]

    return create_error_response(
        message="Request validation failed.",
        error_code="REQUEST_VALIDATION_ERROR",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        request_id=get_request_id(request),
        details={
            "errors": validation_errors,
        },
    )


# ============================================================
# Unexpected exception handler
# ============================================================

async def unexpected_exception_handler(
    request: Request,
    exception: Exception,
) -> JSONResponse:
    """
    Handle unexpected application failures.

    Full exception information is logged internally, while
    clients receive a generic error message.
    """
    request_id = get_request_id(request)

    logger.exception(
        "unhandled_exception",
        exception_type=type(exception).__name__,
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )

    return create_error_response(
        message="An unexpected internal server error occurred.",
        error_code="INTERNAL_SERVER_ERROR",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        request_id=request_id,
    )


# ============================================================
# FastAPI registration
# ============================================================

def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all centralised exception handlers.

    Call this function when constructing the FastAPI application.
    """
    app.add_exception_handler(
        TeleForwardError,
        teleforward_exception_handler,
    )

    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )

    app.add_exception_handler(
        RequestValidationError,
        request_validation_exception_handler,
    )

    app.add_exception_handler(
        Exception,
        unexpected_exception_handler,
    )
