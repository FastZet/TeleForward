
"""
TeleForward asynchronous database session management.

Provides a centralised SQLAlchemy async session factory,
request-scoped session dependencies and transaction helpers.
"""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import TypeVar

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.core.exceptions import DatabaseError
from app.database.engine import get_database_engine


T = TypeVar("T")


# ============================================================
# Session factory
# ============================================================

@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Return the cached asynchronous SQLAlchemy session factory.

    expire_on_commit=False allows ORM objects to remain
    accessible after a transaction has been committed.
    """
    engine = get_database_engine()

    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
        autocommit=False,
    )


# ============================================================
# Session dependency
# ============================================================

async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Yield an asynchronous database session.

    Sessions are automatically closed after use. Pending
    transactions are rolled back if an exception occurs.
    """
    session_factory = get_session_factory()

    async with session_factory() as session:
        try:
            yield session

        except Exception:
            await session.rollback()
            raise


# ============================================================
# Transaction context
# ============================================================

async def get_transaction() -> AsyncIterator[AsyncSession]:
    """
    Yield a session with automatic transaction management.

    Commits when the operation completes successfully and
    rolls back when an exception occurs.

    Use this helper for operations that require a single
    atomic database transaction.
    """
    session_factory = get_session_factory()

    async with session_factory() as session:
        try:
            async with session.begin():
                yield session

        except Exception as exc:
            raise DatabaseError(
                "Database transaction failed."
            ) from exc


# ============================================================
# Session cleanup
# ============================================================

def clear_session_factory_cache() -> None:
    """Clear the cached session factory."""
    get_session_factory.cache_clear()
