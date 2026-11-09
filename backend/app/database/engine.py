
"""
TeleForward asynchronous database engine configuration.

Supports:
- SQLite through aiosqlite.
- PostgreSQL through asyncpg.
- SQLite foreign-key enforcement.
- SQLite connection timeout and busy-timeout configuration.
- Connection pooling and health checks.
"""

from functools import lru_cache

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
)

from app.core.config import get_settings


SQLITE_CONNECT_TIMEOUT = 30
SQLITE_BUSY_TIMEOUT_MS = 30_000


def _configure_sqlite_engine(engine: AsyncEngine) -> None:
    """Apply SQLite-specific connection settings."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(
        dbapi_connection,
        connection_record,
    ) -> None:
        """Enable SQLite foreign keys and configure busy timeout."""

        cursor = dbapi_connection.cursor()

        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(
                f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}"
            )
        finally:
            cursor.close()


@lru_cache(maxsize=1)
def get_database_engine() -> AsyncEngine:
    """
    Return the application's cached asynchronous database engine.

    The engine is created lazily and reused throughout the
    application's lifetime.
    """

    settings = get_settings()
    database_url = settings.effective_database_url
    url = make_url(database_url)

    engine_options = {
        "echo": settings.database_echo,
        "pool_pre_ping": True,
    }

    if url.get_backend_name() == "sqlite":
        engine_options["connect_args"] = {
            "timeout": SQLITE_CONNECT_TIMEOUT,
        }

    else:
        engine_options.update(
            {
                "pool_size": settings.database_pool_size,
                "max_overflow": settings.database_max_overflow,
                "pool_timeout": settings.database_pool_timeout,
                "pool_recycle": settings.database_pool_recycle,
            }
        )

    engine = create_async_engine(
        database_url,
        **engine_options,
    )

    if url.get_backend_name() == "sqlite":
        _configure_sqlite_engine(engine)

    return engine


async def dispose_database_engine() -> None:
    """
    Dispose the cached engine and clear its cache.

    This function should be called during application shutdown.
    """

    engine = get_database_engine()

    try:
        await engine.dispose()
    finally:
        get_database_engine.cache_clear()
