
"""
TeleForward database health diagnostics.

Provides database connectivity checks, dialect identification
and connection latency measurements.
"""

import time
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import get_database_engine


logger = structlog.get_logger(__name__)


async def check_database_connection() -> dict[str, Any]:
    """
    Check database connectivity and measure response time.

    Returns:
        Dictionary containing database health information.
    """
    engine = get_database_engine()

    start_time = time.perf_counter()

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        latency_ms = round(
            (time.perf_counter() - start_time) * 1000,
            2,
        )

        return {
            "status": "healthy",
            "dialect": engine.dialect.name,
            "latency_ms": latency_ms,
        }

    except SQLAlchemyError:
        logger.exception("database_connection_health_check_failed")

        return {
            "status": "unhealthy",
            "dialect": engine.dialect.name,
        }


async def get_database_diagnostics() -> dict[str, Any]:
    """
    Return detailed database diagnostics.

    Provides operational information without exposing
    connection strings, credentials or sensitive data.
    """
    engine = get_database_engine()

    health = await check_database_connection()

    result = {
        "status": health["status"],
        "dialect": health["dialect"],
        "driver": engine.dialect.driver,
    }

    if "latency_ms" in health:
        result["latency_ms"] = health["latency_ms"]

    if engine.dialect.name == "sqlite":
        result["database_type"] = "SQLite"
    elif engine.dialect.name == "postgresql":
        result["database_type"] = "PostgreSQL"
    else:
        result["database_type"] = "Other"

    return result
