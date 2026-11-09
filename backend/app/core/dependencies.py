
"""
TeleForward shared FastAPI dependencies.

Provides reusable dependencies for application settings,
database sessions, authentication and application services.
"""

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings


# ============================================================
# Application configuration
# ============================================================

def get_app_settings() -> Settings:
    """Return the application configuration."""
    return get_settings()


SettingsDependency = Annotated[
    Settings,
    Depends(get_app_settings),
]


# ============================================================
# Database session
# ============================================================

async def get_database_session(
    request: Request,
) -> AsyncIterator[Any]:
    """
    Provide an asynchronous database session.

    The database infrastructure will register its session
    factory as app.state.database_session_factory.

    Each request receives its own session, which is closed
    automatically after the request completes.
    """
    session_factory = getattr(
        request.app.state,
        "database_session_factory",
        None,
    )

    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is not available.",
        )

    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


DatabaseSessionDependency = Annotated[
    Any,
    Depends(get_database_session),
]


# ============================================================
# Authentication context
# ============================================================

async def get_current_user(
    request: Request,
) -> dict[str, Any]:
    """
    Retrieve the authenticated user from request state.

    Authentication middleware or the authentication service
    must populate request.state.current_user.

    Returns:
        Authenticated user context.

    Raises:
        HTTPException: If the request is unauthenticated.
    """
    user = getattr(
        request.state,
        "current_user",
        None,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    return user


CurrentUserDependency = Annotated[
    dict[str, Any],
    Depends(get_current_user),
]


# ============================================================
# Optional authentication context
# ============================================================

async def get_optional_current_user(
    request: Request,
) -> dict[str, Any] | None:
    """
    Retrieve the authenticated user if one exists.

    Unlike get_current_user(), this dependency does not reject
    unauthenticated requests.
    """
    return getattr(
        request.state,
        "current_user",
        None,
    )


OptionalCurrentUserDependency = Annotated[
    dict[str, Any] | None,
    Depends(get_optional_current_user),
]


# ============================================================
# Application readiness
# ============================================================

async def require_application_ready(
    request: Request,
) -> None:
    """
    Reject requests when application startup is incomplete.
    """
    ready = getattr(
        request.app.state,
        "ready",
        False,
    )

    if not ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application is not ready.",
        )


ApplicationReadyDependency = Annotated[
    None,
    Depends(require_application_ready),
]
