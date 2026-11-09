
"""
TeleForward asynchronous database session management.

Provides:
- Cached asynchronous session factory.
- Request-scoped database sessions.
- Explicit transaction management.
- Safe session cleanup.
"""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.core.exceptions import DatabaseError
from app.database.engine import get_database_engine


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Return the cached asynchronous SQLAlchemy session factory.

    Sessions use explicit transaction management and do not
    expire ORM objects automatically after commit.
    """
    engine = get_database_engine()

    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
        autocommit=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session for FastAPI dependency injection.

    The session is always closed after the request completes.
    This dependency does not automatically commit transactions.
    """
    session_factory = get_session_factory()

    async with session_factory() as session:
        try:
            yield session

        except Exception:
            await session.rollback()
            raise

        finally:
            await session.close()


@asynccontextmanager
async def get_transaction() -> AsyncIterator[AsyncSession]:
    """
    Provide a session with an automatically managed transaction.

    Successful execution commits the transaction.
    Exceptions trigger rollback and are propagated unchanged.
    """
    session_factory = get_session_factory()

    async with session_factory() as session:
        try:
            async with session.begin():
                yield session

        except Exception:
            if session.in_transaction():
                await session.rollback()

            raise


async def close_session(session: AsyncSession) -> None:
    """Safely close an individual database session."""
    try:
        await session.close()

    except Exception as exc:
        raise DatabaseError(
            "Unable to close the database session."
        ) from exc


def clear_session_factory_cache() -> None:
    """Clear the cached session factory."""
    get_session_factory.cache_clear()
