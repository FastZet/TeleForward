
"""
TeleForward API-level dependencies.

Provides reusable query-parameter validation for paginated
API endpoints.
"""

from dataclasses import dataclass

from fastapi import Query


DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class PaginationParams:
    """Validated pagination parameters for API list endpoints."""

    page: int = DEFAULT_PAGE
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        """Return the database offset for the requested page."""

        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """Return the maximum number of records to retrieve."""

        return self.page_size


def get_pagination_params(
    page: int = Query(
        default=DEFAULT_PAGE,
        ge=1,
        description="Page number, starting at 1.",
    ),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Number of records per page (maximum {MAX_PAGE_SIZE}).",
    ),
) -> PaginationParams:
    """
    Validate and return pagination parameters.

    FastAPI performs query-parameter validation before invoking
    the endpoint.
    """

    return PaginationParams(
        page=page,
        page_size=page_size,
    )
