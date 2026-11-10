"""Backup and restoration of scheduled-task configurations."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.scheduling.configuration import (
    ScheduledTaskConfigurationSet,
)
from app.services.scheduling.task_config import ScheduledTaskConfig


class ConfigurationBackupError(Exception):
    """Raised when a configuration backup operation fails."""


class ConfigurationBackupService:
    """Create, inspect, and restore configuration snapshots."""

    FORMAT_VERSION = 1
    BACKUP_EXTENSION = ".json"

    def __init__(
        self,
        backup_directory: str | Path,
        *,
        max_backups: int = 20,
    ) -> None:
        if (
            isinstance(max_backups, bool)
            or not isinstance(max_backups, int)
            or max_backups < 1
        ):
            raise ValueError("max_backups must be a positive integer")

        self._directory = Path(backup_directory).expanduser()
        self._max_backups = max_backups

    @property
    def backup_directory(self) -> Path:
        """Return the configured backup directory."""

        return self._directory

    def create_backup(
        self,
        configuration: ScheduledTaskConfigurationSet,
        *,
        label: str | None = None,
    ) -> Path:
        """Write a configuration snapshot and return its path."""

        if not isinstance(
            configuration,
            ScheduledTaskConfigurationSet,
        ):
            raise TypeError(
                "configuration must be a "
                "ScheduledTaskConfigurationSet"
            )

        if label is not None:
            if not isinstance(label, str) or not label.strip():
                raise ValueError("label must be a non-empty string")

        self._directory.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"configuration-{timestamp}{self.BACKUP_EXTENSION}"
        destination = self._directory / filename

        tasks = configuration.to_list()

        payload: dict[str, Any] = {
            "format_version": self.FORMAT_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "label": label.strip() if label else None,
            "task_count": len(tasks),
            "tasks": tasks,
        }

        canonical_payload = self._canonical_json(payload)
        envelope = {
            "payload": payload,
            "sha256": hashlib.sha256(
                canonical_payload
            ).hexdigest(),
        }

        self._write_atomically(destination, envelope)
        self._prune_backups()

        return destination

    def restore_backup(
        self,
        backup_path: str | Path,
    ) -> ScheduledTaskConfigurationSet:
        """Load and validate a configuration snapshot."""

        path = Path(backup_path).expanduser()

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationBackupError(
                f"Unable to read configuration backup: {path}"
            ) from exc

        if not isinstance(raw, dict):
            raise ConfigurationBackupError(
                "Backup root must be a JSON object"
            )

        payload = raw.get("payload")
        checksum = raw.get("sha256")

        if not isinstance(payload, dict):
            raise ConfigurationBackupError(
                "Backup payload is missing or invalid"
            )

        if not isinstance(checksum, str):
            raise ConfigurationBackupError(
                "Backup checksum is missing or invalid"
            )

        actual_checksum = hashlib.sha256(
            self._canonical_json(payload)
        ).hexdigest()

        if not hashlib.compare_digest(
            actual_checksum,
            checksum,
        ):
            raise ConfigurationBackupError(
                "Configuration backup checksum verification failed"
            )

        version = payload.get("format_version")

        if version != self.FORMAT_VERSION:
            raise ConfigurationBackupError(
                f"Unsupported backup format version: {version}"
            )

        tasks = payload.get("tasks")

        if not isinstance(tasks, list):
            raise ConfigurationBackupError(
                "Backup tasks must be a list"
            )

        if payload.get("task_count") != len(tasks):
            raise ConfigurationBackupError(
                "Backup task count does not match its contents"
            )

        try:
            configurations = [
                ScheduledTaskConfig.from_dict(item)
                for item in tasks
            ]

            return ScheduledTaskConfigurationSet.from_iterable(
                configurations
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ConfigurationBackupError(
                "Backup contains invalid task configuration"
            ) from exc

    def list_backups(self) -> list[dict[str, Any]]:
        """List available backups, newest first."""

        if not self._directory.exists():
            return []

        backups: list[dict[str, Any]] = []

        for path in self._directory.glob(
            f"configuration-*{self.BACKUP_EXTENSION}"
        ):
            if not path.is_file():
                continue

            try:
                stat = path.stat()
                backups.append(
                    {
                        "filename": path.name,
                        "path": str(path),
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime,
                            tz=UTC,
                        ).isoformat(),
                    }
                )
            except OSError:
                continue

        return sorted(
            backups,
            key=lambda item: item["modified_at"],
            reverse=True,
        )

    def delete_backup(
        self,
        backup_path: str | Path,
    ) -> bool:
        """Delete a backup located inside the backup directory."""

        path = Path(backup_path).expanduser().resolve()
        directory = self._directory.resolve()

        if path.parent != directory:
            raise ValueError(
                "Backup must be directly inside the backup directory"
            )

        if path.suffix != self.BACKUP_EXTENSION:
            raise ValueError("Invalid backup file extension")

        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def _write_atomically(
        self,
        destination: Path,
        data: dict[str, Any],
    ) -> None:
        """Write JSON through a temporary file and atomic replacement."""

        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=".configuration-backup-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)

                json.dump(
                    data,
                    temporary,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())

            os.replace(temporary_path, destination)
            temporary_path = None

        except (OSError, TypeError, ValueError) as exc:
            raise ConfigurationBackupError(
                f"Unable to create configuration backup: {destination}"
            ) from exc

        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _prune_backups(self) -> None:
        """Retain only the configured number of newest backups."""

        backups = self.list_backups()

        for backup in backups[self._max_backups:]:
            try:
                Path(backup["path"]).unlink(missing_ok=True)
            except OSError:
                # A cleanup failure must not invalidate a completed backup.
                continue

    @staticmethod
    def _canonical_json(payload: dict[str, Any]) -> bytes:
        """Produce deterministic JSON bytes for checksum calculation."""

        try:
            return json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ConfigurationBackupError(
                "Configuration contains non-serializable values"
            ) from exc
