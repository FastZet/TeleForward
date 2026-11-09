
"""
TeleForward database package.

Centralises public database interfaces while keeping engine,
session, migration, and health implementations in their
respective modules.
"""

from app.database.base import (
    Base,
    PrimaryKeyMixin,
    TimestampMixin,
)
from app.database.engine import (
    dispose_database_engine,
    get_database_engine,
)
from app.database.health import (
    check_database_connection,
    get_database_diagnostics,
)
from app.database.init import (
    initialise_database,
    shutdown_database,
)
from app.database.session import (
    clear_session_factory,
    get_session,
    get_session_factory,
    get_transaction,
)


__all__ = [
    "Base",
    "PrimaryKeyMixin",
    "TimestampMixin",
    "get_database_engine",
    "dispose_database_engine",
    "get_session_factory",
    "get_session",
    "get_transaction",
    "clear_session_factory",
    "initialise_database",
    "shutdown_database",
    "check_database_connection",
    "get_database_diagnostics",
]
