"""Audit logging for scheduled-task configuration operations."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


logger = logging.getLogger(__name__)


class ConfigurationAuditAction(StrEnum):
    """Supported configuration audit operations."""

    LOAD = "load"
    REPLACE = "replace"
    PREVIEW = "preview"
    SYNCHRONIZE = "synchronize"
    BACKUP = "backup"
    RESTORE = "restore"
    DELETE_BACKUP = "delete_backup"
    WATCHER_RELOAD = "watcher_reload"


@dataclass(frozen=True, slots=True)
class ConfigurationAuditEntry:
    """Immutable record of a configuration operation."""

    event_id: str
    action: ConfigurationAuditAction
    occurred_at: datetime
    success: bool
    actor: str | None = None
    source: str | None = None
    message: str | None = None
    task_names: tuple[str, ...] = ()
    changes: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id cannot be empty")

        if not isinstance(self.action, ConfigurationAuditAction):
            raise TypeError("action must be a ConfigurationAuditAction")

        if not isinstance(self.occurred_at, datetime):
            raise TypeError("occurred_at must be a datetime")

        if (
            self.occurred_at.tzinfo is None
            or self.occurred_at.utcoffset() is None
        ):
            raise ValueError("occurred_at must be timezone-aware")

        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean")

        if self.actor is not None and not isinstance(self.actor, str):
            raise TypeError("actor must be a string or None")

        if self.source is not None and not isinstance(self.source, str):
            raise TypeError("source must be a string or None")

        if self.message is not None and not isinstance(self.message, str):
            raise TypeError("message must be a string or None")

        if not isinstance(self.task_names, tuple):
            raise TypeError("task_names must be a tuple")

        if not isinstance(self.changes, Mapping):
            raise TypeError("changes must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return {
            "event_id": self.event_id,
            "action": self.action.value,
            "occurred_at": self.occurred_at.isoformat(),
            "success": self.success,
            "actor": self.actor,
            "source": self.source,
            "message": self.message,
            "task_names": list(self.task_names),
            "changes": dict(self.changes),
            "correlation_id": self.correlation_id,
        }


class ConfigurationAuditService:
    """Append and query configuration audit records."""

    def __init__(
        self,
        log_path: str | Path,
        *,
        max_record_bytes: int = 256 * 1024,
        fsync: bool = True,
    ) -> None:
        if (
            isinstance(max_record_bytes, bool)
            or not isinstance(max_record_bytes, int)
            or max_record_bytes < 1024
        ):
            raise ValueError(
                "max_record_bytes must be an integer of at least 1024"
            )

        if not isinstance(fsync, bool):
            raise TypeError("fsync must be a boolean")

        self._path = Path(log_path).expanduser()
        self._max_record_bytes = max_record_bytes
        self._fsync = fsync
        self._lock = threading.RLock()

    @property
    def log_path(self) -> Path:
        """Return the audit log path."""

        return self._path

    def record(
        self,
        action: ConfigurationAuditAction,
        *,
        success: bool,
        actor: str | None = None,
        source: str | None = None,
        message: str | None = None,
        task_names: tuple[str, ...] | list[str] = (),
        changes: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> ConfigurationAuditEntry:
        """Create and persist an audit entry."""

        if not isinstance(action, ConfigurationAuditAction):
            raise TypeError("action must be a ConfigurationAuditAction")

        if not isinstance(success, bool):
            raise TypeError("success must be a boolean")

        if isinstance(task_names, (str, bytes)):
            raise TypeError("task_names must be a sequence of names")

        normalized_names = tuple(task_names)

        if any(
            not isinstance(name, str) or not name.strip()
            for name in normalized_names
        ):
            raise ValueError("task_names must contain non-empty strings")

        if changes is not None and not isinstance(changes, Mapping):
            raise TypeError("changes must be a mapping")

        entry = ConfigurationAuditEntry(
            event_id=str(uuid.uuid4()),
            action=action,
            occurred_at=datetime.now(UTC),
            success=success,
            actor=actor,
            source=source,
            message=message,
            task_names=normalized_names,
            changes=dict(changes or {}),
            correlation_id=correlation_id,
        )

        self._append(entry)

        return entry

    def read(
        self,
        *,
        action: ConfigurationAuditAction | None = None,
        success: bool | None = None,
        limit: int = 100,
        before: datetime | None = None,
    ) -> list[ConfigurationAuditEntry]:
        """Read audit entries, newest first."""

        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")

        if action is not None and not isinstance(
            action,
            ConfigurationAuditAction,
        ):
            raise TypeError("action must be a ConfigurationAuditAction")

        if success is not None and not isinstance(success, bool):
            raise TypeError("success must be a boolean")

        if before is not None:
            if (
                not isinstance(before, datetime)
                or before.tzinfo is None
                or before.utcoffset() is None
            ):
                raise ValueError("before must be timezone-aware")

        if not self._path.exists():
            return []

        entries: list[ConfigurationAuditEntry] = []

        with self._lock:
            try:
                with self._path.open("r", encoding="utf-8") as stream:
                    for line_number, line in enumerate(stream, start=1):
                        if not line.strip():
                            continue

                        try:
                            raw = json.loads(line)
                            entry = self._from_dict(raw)
                        except (
                            json.JSONDecodeError,
                            TypeError,
                            ValueError,
                            KeyError,
                        ):
                            logger.warning(
                                "Skipping invalid audit record at line %s",
                                line_number,
                            )
                            continue

                        if action is not None and entry.action != action:
                            continue

                        if success is not None and entry.success != success:
                            continue

                        if before is not None and entry.occurred_at >= before:
                            continue

                        entries.append(entry)

            except OSError:
                logger.exception("Unable to read configuration audit log")
                raise

        entries.sort(
            key=lambda entry: entry.occurred_at,
            reverse=True,
        )

        return entries[:limit]

    def count(self) -> int:
        """Return the number of valid audit records."""

        if not self._path.exists():
            return 0

        total = 0

        with self._lock:
            try:
                with self._path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        if not line.strip():
                            continue

                        try:
                            self._from_dict(json.loads(line))
                            total += 1
                        except (
                            json.JSONDecodeError,
                            TypeError,
                            ValueError,
                            KeyError,
                        ):
                            continue

            except OSError:
                logger.exception("Unable to count audit records")
                raise

        return total

    def _append(self, entry: ConfigurationAuditEntry) -> None:
        """Append one validated record to the JSON Lines log."""

        try:
            serialized = json.dumps(
                entry.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )

            encoded = (serialized + "\n").encode("utf-8")

            if len(encoded) > self._max_record_bytes:
                raise ValueError(
                    "Audit record exceeds the configured size limit"
                )

            self._path.parent.mkdir(parents=True, exist_ok=True)

            with self._lock:
                descriptor = os.open(
                    self._path,
                    os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                    0o600,
                )

                try:
                    with os.fdopen(descriptor, "ab") as stream:
                        descriptor = -1
                        stream.write(encoded)
                        stream.flush()

                        if self._fsync:
                            os.fsync(stream.fileno())
                finally:
                    if descriptor != -1:
                        os.close(descriptor)

        except (OSError, TypeError, ValueError) as exc:
            logger.exception("Failed to write configuration audit record")
            raise RuntimeError(
                "Unable to persist configuration audit record"
            ) from exc

    @staticmethod
    def _from_dict(raw: Any) -> ConfigurationAuditEntry:
        """Validate and reconstruct an audit entry."""

        if not isinstance(raw, dict):
            raise TypeError("Audit record must be an object")

        occurred_at = datetime.fromisoformat(raw["occurred_at"])

        return ConfigurationAuditEntry(
            event_id=raw["event_id"],
            action=ConfigurationAuditAction(raw["action"]),
            occurred_at=occurred_at,
            success=raw["success"],
            actor=raw.get("actor"),
            source=raw.get("source"),
            message=raw.get("message"),
            task_names=tuple(raw.get("task_names", ())),
            changes=raw.get("changes", {}),
            correlation_id=raw.get("correlation_id"),
        )
