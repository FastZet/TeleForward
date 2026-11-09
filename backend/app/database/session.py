
"""
TeleForward asynchronous database session management.

Provides:
- A cached asynchronous session factory.
- Request-scoped database sessions.
- Explicit transaction-scoped sessions.
- Session-factory cache cleanup.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.database.engine import get_database_engine


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Return the cached asynchronous SQLAlchemy session factory.

    Sessions do not expire ORM objects automatically after commit,
    allowing services to access committed object attributes without
    requiring an immediate database refresh.
    """

    return async_sessionmaker(
        bind=get_database_engine(),
        class_=AsyncSession,
        autoflush=True,
        expire_on_commit=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Provide a database session without automatic commit.

    Intended for FastAPI dependency injection.

    Transaction commits must be performed explicitly by the
    application service. Any unfinished transaction is rolled
    back when the session scope ends.
    """

    session_factory = get_session_factory()

    async with session_factory() as session:
        try:
            yield session
        except BaseException:
            if session.in_transaction():
                await session.rollback()
            raise
        finally:
            if session.in_transaction():
                await session.rollback()


async def get_transaction() -> AsyncIterator[AsyncSession]:
    """
    Provide a session with an automatically managed transaction.

    The transaction commits when the context exits successfully
    and rolls back if an exception occurs.

    Intended for operations that must execute atomically.
    """

    session_factory = get_session_factory()

    async with session_factory() as session:
        async with session.begin():
            yield session


def clear_session_factory() -> None:
    """
    Clear the cached session factory.

    Call during database shutdown or when replacing the engine.
    This does not dispose the underlying database engine.
    """

    get_session_factory.cache_clear()
