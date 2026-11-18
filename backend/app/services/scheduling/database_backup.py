"""Atomic SQLite database backups for scheduled maintenance."""

from __future__ import annotations

import asyncio
import os
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import make_url

from app.services.scheduling.base import ScheduledTaskContext


class SQLiteDatabaseBackup:
    """Create online SQLite backups without blocking the event loop."""

    def __init__(
        self,
        database_path: str | Path,
        backup_directory: str | Path,
    ) -> None:
        self._database_path = Path(database_path).expanduser().resolve()
        self._backup_directory = Path(backup_directory).expanduser().resolve()

    async def __call__(
        self,
        context: ScheduledTaskContext,
    ) -> Mapping[str, Any]:
        if not isinstance(context, ScheduledTaskContext):
            raise TypeError("context must be a ScheduledTaskContext")
        return await asyncio.to_thread(self._create_backup)

    def _create_backup(self) -> Mapping[str, Any]:
        if not self._database_path.is_file():
            raise FileNotFoundError(
                "Configured SQLite database file does not exist"
            )

        self._backup_directory.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        try:
            self._backup_directory.chmod(0o700)
        except OSError:
            # The backup file itself is still created with mode 0600.
            pass

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_id = f"{timestamp}-{uuid4().hex[:12]}"
        destination = self._backup_directory / (
            f"teleforward-{backup_id}.sqlite3"
        )
        temporary = self._backup_directory / (
            f".{destination.name}.tmp"
        )

        source_connection = None
        target_connection = None
        try:
            source_connection = sqlite3.connect(
                str(self._database_path),
                timeout=30,
            )
            target_connection = sqlite3.connect(
                str(temporary),
                timeout=30,
            )
            target_connection.execute("PRAGMA journal_mode=DELETE")
            source_connection.backup(target_connection)
            integrity = target_connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError("SQLite backup integrity check failed")
            target_connection.close()
            target_connection = None
            source_connection.close()
            source_connection = None

            os.chmod(temporary, 0o600)
            with temporary.open("rb") as backup_file:
                os.fsync(backup_file.fileno())
            os.replace(temporary, destination)

            return {
                "success": True,
                "backup_id": backup_id,
                "size_bytes": destination.stat().st_size,
                "format": "sqlite3",
                "location": str(destination),
            }
        except Exception:
            if target_connection is not None:
                target_connection.close()
            if source_connection is not None:
                source_connection.close()
            temporary.unlink(missing_ok=True)
            raise


def build_sqlite_backup_operation(
    database_url: str,
    backup_directory: str | Path,
) -> Callable[
    [ScheduledTaskContext],
    Awaitable[Mapping[str, Any]],
] | None:
    """Return a backup operation only for file based SQLite URLs."""
    url = make_url(database_url)
    database_path = url.database

    if (
        url.get_backend_name() != "sqlite"
        or not database_path
        or database_path == ":memory:"
    ):
        return None

    return SQLiteDatabaseBackup(
        database_path,
        backup_directory,
    )
