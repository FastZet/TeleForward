
"""
TeleForward asynchronous database engine.

Configures SQLAlchemy 2.x asynchronous database connectivity
for SQLite and PostgreSQL.
"""

from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.exceptions import ConfigurationError


def _get_engine_options(database_url: str) -> dict[str, Any]:
    """
    Return database-specific SQLAlchemy engine options.

    SQLite:
        Enables foreign key enforcement and configures a
        connection timeout.

    PostgreSQL:
        Configures connection pooling.
    """
    if database_url.startswith("sqlite+aiosqlite://"):
        return {
            "echo": False,
            "connect_args": {
                "timeout": 30,
            },
        }

    if database_url.startswith("postgresql+asyncpg://"):
        return {
            "echo": False,
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
            "pool_recycle": 1800,
            "pool_pre_ping": True,
        }

    raise ConfigurationError(
        "Unsupported database URL. Use SQLite or PostgreSQL "
        "with an asynchronous SQLAlchemy driver."
    )


@lru_cache(maxsize=1)
def get_database_engine() -> AsyncEngine:
    """
    Create and return the cached asynchronous database engine.

    Returns:
        SQLAlchemy AsyncEngine.

    Raises:
        ConfigurationError: If the database URL is unsupported.
    """
    settings = get_settings()
    database_url = settings.effective_database_url

    options = _get_engine_options(database_url)

    return create_async_engine(
        database_url,
        **options,
    )


async def dispose_database_engine() -> None:
    """
    Dispose of the cached database engine.

    Should be called during application shutdown to release
    database connections cleanly.
    """
    if get_database_engine.cache_info().currsize == 0:
        return

    engine = get_database_engine()

    await engine.dispose()

    get_database_engine.cache_clear()
