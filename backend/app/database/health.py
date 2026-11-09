
"""
TeleForward database health monitoring and diagnostics.

Provides:
- Database connectivity checks.
- Connection latency measurement.
- Database dialect and driver information.
- Safe connection-pool diagnostics.
"""

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database.engine import get_database_engine


async def check_database_connection() -> dict[str, Any]:
    """
    Check database connectivity and measure response latency.

    Returns a structured result suitable for health endpoints.
    Does not expose connection strings or credentials.
    """

    started_at = perf_counter()

    try:
        engine = get_database_engine()

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        latency_ms = round(
            (perf_counter() - started_at) * 1000,
            2,
        )

        return {
            "status": "healthy",
            "connected": True,
            "latency_ms": latency_ms,
            "dialect": engine.dialect.name,
            "driver": engine.dialect.driver,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    except SQLAlchemyError as exc:
        return {
            "status": "unhealthy",
            "connected": False,
            "error": type(exc).__name__,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        return {
            "status": "unhealthy",
            "connected": False,
            "error": type(exc).__name__,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


def get_database_diagnostics() -> dict[str, Any]:
    """
    Return safe database engine and connection-pool diagnostics.

    Pool statistics are operational metadata only. No credentials,
    database URLs, or SQL statements are exposed.
    """

    try:
        engine = get_database_engine()
        pool = engine.pool

        diagnostics: dict[str, Any] = {
            "dialect": engine.dialect.name,
            "driver": engine.dialect.driver,
            "pool_class": type(pool).__name__,
        }

        pool_methods = {
            "pool_size": "size",
            "checked_in_connections": "checkedin",
            "checked_out_connections": "checkedout",
            "overflow_connections": "overflow",
        }

        for output_key, method_name in pool_methods.items():
            method = getattr(pool, method_name, None)

            if callable(method):
                try:
                    diagnostics[output_key] = method()
                except Exception:
                    diagnostics[output_key] = None

        return diagnostics

    except Exception as exc:
        return {
            "status": "unavailable",
            "error": type(exc).__name__,
        }
