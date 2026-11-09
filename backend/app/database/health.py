
"""
TeleForward database health diagnostics.

Provides connection checks, latency measurements and safe
database metadata for application health monitoring.
"""

import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import get_database_engine


logger = logging.getLogger(__name__)


async def check_database_connection() -> dict[str, Any]:
    """
    Check database connectivity and measure response latency.

    Returns a structured health result without exposing
    connection strings or credentials.
    """
    started_at = time.perf_counter()

    try:
        engine = get_database_engine()

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        latency_ms = round(
            (time.perf_counter() - started_at) * 1000,
            2,
        )

        return {
            "status": "healthy",
            "latency_ms": latency_ms,
            "database": engine.dialect.name,
            "driver": engine.dialect.driver,
        }

    except SQLAlchemyError:
        logger.exception("Database health check failed.")

        return {
            "status": "unhealthy",
            "latency_ms": None,
            "database": None,
            "driver": None,
            "error": "Database connection or query failed.",
        }

    except Exception:
        logger.exception(
            "Unexpected error during database health check."
        )

        return {
            "status": "unhealthy",
            "latency_ms": None,
            "database": None,
            "driver": None,
            "error": "Database health check could not be completed.",
        }


async def get_database_diagnostics() -> dict[str, Any]:
    """
    Return safe database diagnostics.

    Includes dialect and driver information without returning
    database URLs, usernames, passwords or filesystem paths.
    """
    try:
        engine = get_database_engine()

        return {
            "configured": True,
            "dialect": engine.dialect.name,
            "driver": engine.dialect.driver,
            "pool": type(engine.pool).__name__,
            "pool_size": (
                engine.pool.size()
                if hasattr(engine.pool, "size")
                else None
            ),
            "checked_out_connections": (
                engine.pool.checkedout()
                if hasattr(engine.pool, "checkedout")
                else None
            ),
        }

    except Exception:
        logger.exception(
            "Unable to retrieve database diagnostics."
        )

        return {
            "configured": False,
            "dialect": None,
            "driver": None,
            "pool": None,
            "pool_size": None,
            "checked_out_connections": None,
        }
