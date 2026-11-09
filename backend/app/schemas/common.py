
"""
TeleForward shared Pydantic schema definitions.

Provides:
- Common schema configuration.
- ORM-compatible response schemas.
- Strict request schema configuration.
- Reusable identifier and pagination types.
"""

from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


PositiveID = Annotated[
    int,
    Field(gt=0),
]

PositivePage = Annotated[
    int,
    Field(ge=1),
]

PageSize = Annotated[
    int,
    Field(ge=1, le=100),
]


class BaseSchema(BaseModel):
    """
    Base class for TeleForward Pydantic schemas.

    Supports ORM attribute extraction and ignores unknown
    fields by default for forward-compatible response handling.
    """

    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
        populate_by_name=True,
        use_enum_values=True,
    )


class RequestSchema(BaseSchema):
    """
    Base class for API request schemas.

    Rejects unexpected fields to catch client-side mistakes
    rather than silently accepting unsupported input.
    """

    model_config = ConfigDict(
        from_attributes=False,
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ResponseSchema(BaseSchema):
    """
    Base class for API response schemas.

    Allows construction from SQLAlchemy ORM objects.
    """

    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
        populate_by_name=True,
        use_enum_values=True,
    )


class PaginatedRequestSchema(RequestSchema):
    """Reusable pagination parameters for request bodies."""

    page: PositivePage = 1
    page_size: PageSize = 20


class MetadataSchema(BaseSchema):
    """Generic metadata container for API data-transfer objects."""

    metadata: dict[str, Any] = Field(default_factory=dict)
