
"""
TeleForward database initialisation.

Provides database connectivity verification, optional development
schema creation, and production Alembic migration execution.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text

from app.core.config import get_settings
from app.core.exceptions import DatabaseError
from app.database.base import Base
from app.database.engine import get_database_engine
from app.database.session import clear_session_factory_cache
import app.models  # noqa: F401 - register all ORM models


logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = BACKEND_DIR / "alembic.ini"


async def verify_database_connection() -> None:
    """Verify that the configured database is reachable."""
    engine = get_database_engine()

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        logger.info("Database connection verified.")

    except Exception as exc:
        logger.exception("Database connection verification failed.")
        raise DatabaseError(
            "Unable to connect to the configured database."
        ) from exc


async def create_initial_schema() -> None:
    """
    Create database tables directly from registered ORM models.

    Intended for development and testing only. Production schema
    changes must be managed through Alembic migrations.
    """
    engine = get_database_engine()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        logger.info("Initial database schema created.")

    except Exception as exc:
        logger.exception("Initial database schema creation failed.")
        raise DatabaseError(
            "Unable to create the initial database schema."
        ) from exc


async def run_database_migrations(
    timeout_seconds: int = 300,
) -> None:
    """
    Apply pending Alembic migrations.

    Runs Alembic in a separate Python process because the migration
    environment uses asyncio.run() and must not execute inside the
    application's running event loop.
    """
    if not ALEMBIC_CONFIG_PATH.is_file():
        raise DatabaseError(
            f"Alembic configuration not found: {ALEMBIC_CONFIG_PATH}"
        )

    command = [
        sys.executable,
        "-m",
        "alembic",
        "-c",
        str(ALEMBIC_CONFIG_PATH),
        "upgrade",
        "head",
    ]

    environment = os.environ.copy()

    logger.info("Applying pending database migrations.")

    process = None

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(BACKEND_DIR),
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            output, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )

        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()

            raise DatabaseError(
                f"Database migrations exceeded the "
                f"{timeout_seconds}-second timeout."
            )

        output_text = output.decode(
            "utf-8",
            errors="replace",
        ).strip()

        if output_text:
            for line in output_text.splitlines():
                logger.info("Alembic: %s", line)

        if process.returncode != 0:
            raise DatabaseError(
                "Database migrations failed. "
                f"Exit code: {process.returncode}. "
                "Review the application logs for details."
            )

        logger.info("Database migrations completed successfully.")

    except DatabaseError:
        raise

    except Exception as exc:
        if process is not None and process.returncode is None:
            process.kill()
            await process.communicate()

        logger.exception("Database migration execution failed.")

        raise DatabaseError(
            "Unable to execute database migrations."
        ) from exc


async def initialise_database(
    *,
    apply_migrations: bool = True,
    create_schema: bool = False,
) -> None:
    """
    Initialise and verify the application database.

    Args:
        apply_migrations:
            Apply pending Alembic migrations. Enabled by default.

        create_schema:
            Create tables directly from ORM metadata instead of
            applying migrations. Intended for development/testing.
    """
    if apply_migrations and create_schema:
        raise ValueError(
            "Cannot enable both Alembic migrations and direct "
            "schema creation."
        )

    logger.info("Initialising TeleForward database.")

    # Ensure cached session factories are recreated if necessary.
    clear_session_factory_cache()

    settings = get_settings()

    if not settings.effective_database_url:
        raise DatabaseError(
            "No database connection URL is configured."
        )

    # Verify that the database server or file is accessible.
    await verify_database_connection()

    if apply_migrations:
        await run_database_migrations()

    elif create_schema:
        await create_initial_schema()

    # Verify connectivity after schema operations.
    await verify_database_connection()

    logger.info("TeleForward database initialisation completed.")


async def shutdown_database() -> None:
    """Dispose database resources during application shutdown."""
    from app.database.engine import dispose_database_engine

    logger.info("Shutting down database connections.")

    try:
        clear_session_factory_cache()
        await dispose_database_engine()

        logger.info("Database connections closed.")

    except Exception as exc:
        logger.exception("Database shutdown failed.")

        raise DatabaseError(
            "Unable to shut down database connections cleanly."
        ) from exc
