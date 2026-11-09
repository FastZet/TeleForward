
"""
TeleForward persistent storage paths.

Defines and manages application directories for databases,
Telegram sessions, logs, backups, temporary files and uploads.
"""

from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import StorageError


@dataclass(frozen=True, slots=True)
class StoragePaths:
    """Immutable collection of application storage paths."""

    root: Path
    database: Path
    sessions: Path
    logs: Path
    backups: Path
    temporary: Path
    uploads: Path
    exports: Path


def get_storage_paths() -> StoragePaths:
    """
    Resolve all application storage paths.

    All runtime data is stored beneath TELEFORWARD_DATA_DIR.

    Returns:
        StoragePaths containing the resolved directory paths.
    """
    settings = get_settings()

    root = settings.data_dir.expanduser().resolve()

    return StoragePaths(
        root=root,
        database=root,
        sessions=root / "sessions",
        logs=root / "logs",
        backups=root / "backups",
        temporary=root / "tmp",
        uploads=root / "uploads",
        exports=root / "exports",
    )


def initialise_storage() -> StoragePaths:
    """
    Create the application storage directory structure.

    Directories are created only when explicitly requested.
    Existing directories and their contents are preserved.

    Raises:
        StorageError: If a directory cannot be created.
    """
    paths = get_storage_paths()

    directories = (
        paths.root,
        paths.sessions,
        paths.logs,
        paths.backups,
        paths.temporary,
        paths.uploads,
        paths.exports,
    )

    try:
        for directory in directories:
            directory.mkdir(
                parents=True,
                exist_ok=True,
                mode=0o700,
            )

    except OSError as exc:
        raise StorageError(
            "Unable to initialise application storage.",
            details={
                "directory": str(directory),
            },
        ) from exc

    return paths


def validate_storage() -> None:
    """
    Validate that application storage is available and writable.

    This function does not create directories. Call
    initialise_storage() before validation during startup.
    """
    paths = get_storage_paths()

    if not paths.root.exists() or not paths.root.is_dir():
        raise StorageError(
            "Application storage directory does not exist."
        )

    if not paths.root.is_dir():
        raise StorageError(
            "Application storage path is not a directory."
        )

    if not paths.root.exists():
        raise StorageError(
            "Application storage directory is unavailable."
        )

    if not paths.root.is_dir():
        raise StorageError(
            "Application storage path is invalid."
        )

    if not paths.root.stat().st_mode & 0o222:
        raise StorageError(
            "Application storage directory has no write permission."
        )

    try:
        probe = paths.root / ".teleforward-write-test"

        with probe.open("x", encoding="utf-8") as file:
            file.write("storage-check")

        probe.unlink()

    except FileExistsError:
        try:
            probe.unlink()
        except OSError:
            pass

    except OSError as exc:
        raise StorageError(
            "Application storage is not writable."
        ) from exc
