
"""
TeleForward ORM models package.

Central registry for all SQLAlchemy database models.

Import model modules here as they are implemented so that
SQLAlchemy metadata and Alembic can discover their tables.
"""

from app.database.base import Base

__all__ = [
    "Base",
]
