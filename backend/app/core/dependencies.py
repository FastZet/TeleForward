
"""
TeleForward shared FastAPI dependencies.

Provides reusable dependencies for:
- Application configuration.
- Database sessions.
- Authenticated users.
- Optional authentication.
- Superuser authorisation.
- Application readiness.
"""

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.database.session import get_session
from app.models.user import User


def get_application_settings() -> Settings:
    """Return the cached application settings."""
    return get_settings()


async def get_database_session() -> AsyncIterator[AsyncSession]:
    """
    Provide a database session for the lifetime of a request.

    Transaction boundaries are deliberately controlled by
    application services rather than automatically committing
    every request.
    """
    async for session in get_session():
        yield session


async def get_current_user(request: Request) -> User:
    """
    Retrieve the authenticated user from request state.

    Authentication middleware or an authentication dependency
    must populate request.state.current_user.
    """
    user = getattr(request.state, "current_user", None)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTHENTICATION_REQUIRED",
                "message": "Authentication is required.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not isinstance(user, User):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_AUTHENTICATION_CONTEXT",
                "message": "The authentication context is invalid.",
            },
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_DISABLED",
                "message": "This account is disabled.",
            },
        )

    return user


async def get_optional_current_user(
    request: Request,
) -> User | None:
    """
    Retrieve the authenticated user when one is available.

    Unlike get_current_user(), this dependency does not reject
    unauthenticated requests.
    """
    user = getattr(request.state, "current_user", None)

    if user is None:
        return None

    if not isinstance(user, User):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_AUTHENTICATION_CONTEXT",
                "message": "The authentication context is invalid.",
            },
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_DISABLED",
                "message": "This account is disabled.",
            },
        )

    return user


async def get_current_superuser(
    current_user: Annotated[
        User,
        Depends(get_current_user),
    ],
) -> User:
    """Require an authenticated superuser."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SUPERUSER_REQUIRED",
                "message": "Superuser privileges are required.",
            },
        )

    return current_user


async def require_application_ready(
    request: Request,
) -> None:
    """
    Reject requests while mandatory application services
    are not ready.
    """
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "APPLICATION_NOT_READY",
                "message": "The application is not ready to serve requests.",
            },
            headers={"Retry-After": "5"},
        )


# Reusable dependency annotations.

ApplicationSettings = Annotated[
    Settings,
    Depends(get_application_settings),
]

DatabaseSession = Annotated[
    AsyncSession,
    Depends(get_database_session),
]

CurrentUser = Annotated[
    User,
    Depends(get_current_user),
]

OptionalCurrentUser = Annotated[
    User | None,
    Depends(get_optional_current_user),
]

CurrentSuperuser = Annotated[
    User,
    Depends(get_current_superuser),
]

ApplicationReady = Annotated[
    None,
    Depends(require_application_ready),
]
