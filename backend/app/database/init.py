
"""
TeleForward database initialisation.

Provides database connectivity checks, initial schema creation
and database shutdown utilities.

Alembic migrations remain the authoritative mechanism for
production schema upgrades.
"""

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import DatabaseError
from app.database.base import Base
from app.database.engine import (
    dispose_database_engine,
    get_database_engine,
)
from app.database.session import clear_session_factory_cache


logger = structlog.get_logger(__name__)


# ============================================================
# Database connectivity
# ============================================================

async def verify_database_connection() -> bool:
    """
    Verify that the configured database is accessible.

    Returns:
        True when the database responds successfully.

    Raises:
        DatabaseError: If the database connection fails.
    """
    engine = get_database_engine()

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        logger.info("database_connection_verified")

        return True

    except SQLAlchemyError as exc:
        logger.exception("database_connection_failed")

        raise DatabaseError(
            "Unable to connect to the configured database."
        ) from exc


# ============================================================
# Initial schema creation
# ============================================================

async def create_initial_schema() -> None:
    """
    Create database tables from registered ORM metadata.

    This operation is intended for initial development or
    controlled bootstrap environments.

    Production schema changes should be applied through
    Alembic migrations instead.
    """
    engine = get_database_engine()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                Base.metadata.create_all
            )

        logger.info("database_initial_schema_created")

    except SQLAlchemyError as exc:
        logger.exception("database_schema_creation_failed")

        raise DatabaseError(
            "Unable to create the initial database schema."
        ) from exc


# ============================================================
# Database initialisation
# ============================================================

async def initialise_database(
    *,
    create_schema: bool = False,
) -> None:
    """
    Initialise database connectivity and optionally create tables.

    Args:
        create_schema:
            When True, create missing tables using ORM metadata.
            Leave False when Alembic migrations manage the schema.

    Raises:
        DatabaseError: If initialisation fails.
    """
    logger.info("database_initialisation_started")

    try:
        await verify_database_connection()

        if create_schema:
            await create_initial_schema()

        logger.info("database_initialisation_completed")

    except DatabaseError:
        raise

    except Exception as exc:
        logger.exception("database_initialisation_failed")

        raise DatabaseError(
            "Database initialisation failed."
        ) from exc


# ============================================================
# Database shutdown
# ============================================================

async def shutdown_database() -> None:
    """
    Dispose of database connections and clear cached factories.

    Call this during application shutdown after database-dependent
    background workers and services have stopped.
    """
    logger.info("database_shutdown_started")

    try:
        clear_session_factory_cache()
        await dispose_database_engine()

        logger.info("database_shutdown_completed")

    except Exception as exc:
        logger.exception("database_shutdown_failed")

        raise DatabaseError(
            "Database shutdown failed."
        ) from exc
