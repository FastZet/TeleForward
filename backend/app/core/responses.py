
"""
TeleForward API response schemas.

Defines reusable response structures for successful operations,
errors, and paginated API results.
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standard API response envelope."""

    success: bool = True
    message: str = "Request completed successfully."
    data: T | None = None


class APIErrorResponse(BaseModel):
    """Standard API error response."""

    success: bool = False
    message: str = "The request could not be completed."
    error_code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PaginationMetadata(BaseModel):
    """Pagination information for collection endpoints."""

    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_next: bool
    has_previous: bool

    @classmethod
    def create(
        cls,
        *,
        page: int,
        page_size: int,
        total_items: int,
    ) -> "PaginationMetadata":
        """Calculate pagination metadata."""
        if page < 1:
            raise ValueError("Page must be at least 1.")

        if page_size < 1:
            raise ValueError("Page size must be at least 1.")

        if total_items < 0:
            raise ValueError("Total items cannot be negative.")

        total_pages = (
            (total_items + page_size - 1) // page_size
        )

        return cls(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1 and total_pages > 0,
        )


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated API response."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool = True
    message: str = "Records retrieved successfully."
    data: list[T]
    pagination: PaginationMetadata


def success_response(
    data: Any = None,
    message: str = "Request completed successfully.",
) -> APIResponse[Any]:
    """
    Construct a standard successful API response.
    """
    return APIResponse(
        success=True,
        message=message,
        data=data,
    )


def error_response(
    message: str,
    *,
    error_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> APIErrorResponse:
    """
    Construct a standard API error response.
    """
    return APIErrorResponse(
        success=False,
        message=message,
        error_code=error_code,
        details=details or {},
    )
