
"""
TeleForward asynchronous database engine configuration.

Supports:
- SQLite through aiosqlite.
- PostgreSQL through asyncpg.

Provides connection pooling, SQLite integrity settings and
centralised engine lifecycle management.
"""

from functools import lru_cache

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.exceptions import ConfigurationError


def _configure_sqlite_engine(engine: AsyncEngine) -> None:
    """
    Configure SQLite connection-level settings.

    SQLite foreign-key enforcement is disabled by default.
    Enable it on every new connection.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(
        dbapi_connection,
        connection_record,
    ) -> None:
        """Apply SQLite PRAGMA settings to each connection."""
        cursor = dbapi_connection.cursor()

        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


@lru_cache(maxsize=1)
def get_database_engine() -> AsyncEngine:
    """
    Return the cached asynchronous SQLAlchemy engine.

    The database URL is obtained from application settings.
    Unsupported database drivers raise ConfigurationError.
    """
    settings = get_settings()
    database_url = settings.effective_database_url

    if not database_url:
        raise ConfigurationError(
            "A database connection URL must be configured."
        )

    common_options = {
        "echo": False,
        "pool_pre_ping": True,
    }

    if database_url.startswith("sqlite+aiosqlite://"):
        engine = create_async_engine(
            database_url,
            connect_args={
                "timeout": 30,
            },
            **common_options,
        )

        _configure_sqlite_engine(engine)

        return engine

    if database_url.startswith("postgresql+asyncpg://"):
        return create_async_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=1800,
            **common_options,
        )

    raise ConfigurationError(
        "Unsupported database URL. "
        "Supported drivers are sqlite+aiosqlite and "
        "postgresql+asyncpg."
    )


async def dispose_database_engine() -> None:
    """
    Dispose the cached database engine.

    This closes pooled connections during application shutdown.
    """
    engine = get_database_engine()

    await engine.dispose()

    get_database_engine.cache_clear()
