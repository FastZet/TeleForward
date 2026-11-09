
"""
TeleForward standard API response schemas.

Provides consistent response envelopes, structured errors,
pagination metadata, and response factory functions.
"""

from math import ceil
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standard successful API response."""

    success: bool = True
    message: str = "Request completed successfully."
    data: T | None = None
    meta: dict[str, Any] | None = None


class APIErrorDetail(BaseModel):
    """Structured API error information."""

    code: str = Field(
        min_length=1,
        description="Machine-readable error identifier.",
    )
    message: str = Field(
        min_length=1,
        description="Human-readable error description.",
    )
    details: dict[str, Any] | list[Any] | None = None


class APIErrorResponse(BaseModel):
    """Standard unsuccessful API response."""

    success: bool = False
    error: APIErrorDetail


class PaginationMetadata(BaseModel):
    """Metadata describing a paginated response."""

    model_config = ConfigDict(
        populate_by_name=True,
    )

    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_previous: bool
    has_next: bool

    @classmethod
    def create(
        cls,
        page: int,
        page_size: int,
        total_items: int,
    ) -> "PaginationMetadata":
        """Calculate pagination metadata."""
        if page < 1:
            raise ValueError("Page must be greater than or equal to 1.")

        if page_size < 1:
            raise ValueError(
                "Page size must be greater than or equal to 1."
            )

        if total_items < 0:
            raise ValueError(
                "Total items cannot be negative."
            )

        total_pages = ceil(total_items / page_size)

        return cls(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_previous=page > 1 and total_pages > 0,
            has_next=page < total_pages,
        )


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated API response."""

    success: bool = True
    message: str = "Request completed successfully."
    data: list[T]
    pagination: PaginationMetadata


def success_response(
    data: Any = None,
    message: str = "Request completed successfully.",
    meta: dict[str, Any] | None = None,
) -> APIResponse[Any]:
    """Create a successful API response."""
    return APIResponse(
        success=True,
        message=message,
        data=data,
        meta=meta,
    )


def error_response(
    code: str,
    message: str,
    details: dict[str, Any] | list[Any] | None = None,
) -> APIErrorResponse:
    """Create a structured API error response."""
    return APIErrorResponse(
        success=False,
        error=APIErrorDetail(
            code=code,
            message=message,
            details=details,
        ),
    )


def paginated_response(
    data: list[T],
    page: int,
    page_size: int,
    total_items: int,
    message: str = "Request completed successfully.",
) -> PaginatedResponse[T]:
    """Create a paginated API response."""
    return PaginatedResponse(
        success=True,
        message=message,
        data=data,
        pagination=PaginationMetadata.create(
            page=page,
            page_size=page_size,
            total_items=total_items,
        ),
    )
