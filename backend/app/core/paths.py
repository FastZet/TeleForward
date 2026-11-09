
"""
TeleForward persistent storage management.

Defines and initialises application storage directories,
validates filesystem access, and protects sensitive data.
"""

import logging
import os
import stat
from pathlib import Path
from typing import Final

from app.core.config import get_settings
from app.core.exceptions import StorageError


logger = logging.getLogger(__name__)


DIRECTORY_PERMISSIONS: Final[int] = 0o750
SENSITIVE_DIRECTORY_PERMISSIONS: Final[int] = 0o700
FILE_PERMISSIONS: Final[int] = 0o600

STORAGE_DIRECTORIES: Final[tuple[str, ...]] = (
    "backups",
    "logs",
    "media",
    "sessions",
    "secrets",
    "temporary",
)

SENSITIVE_DIRECTORIES: Final[frozenset[str]] = frozenset({
    "sessions",
    "secrets",
})


def get_data_directory() -> Path:
    """Return the resolved application data directory."""
    settings = get_settings()

    return Path(settings.data_dir).expanduser().resolve()


def get_storage_paths() -> dict[str, Path]:
    """Return all configured persistent storage paths."""
    root = get_data_directory()

    paths = {
        "root": root,
    }

    for directory_name in STORAGE_DIRECTORIES:
        paths[directory_name] = root / directory_name

    return paths


def _ensure_directory(
    path: Path,
    permissions: int,
) -> None:
    """Create a directory and enforce its intended permissions."""
    try:
        path.mkdir(
            parents=True,
            exist_ok=True,
            mode=permissions,
        )

        if not path.is_dir():
            raise StorageError(
                f"Storage path is not a directory: {path.name}"
            )

        path.chmod(permissions)

    except StorageError:
        raise

    except OSError as exc:
        raise StorageError(
            f"Unable to initialise storage directory: {path.name}"
        ) from exc


def initialise_storage() -> dict[str, Path]:
    """
    Create all required persistent storage directories.

    Sensitive directories receive restrictive permissions.
    """
    paths = get_storage_paths()

    root = paths["root"]

    _ensure_directory(
        root,
        DIRECTORY_PERMISSIONS,
    )

    for directory_name in STORAGE_DIRECTORIES:
        permissions = (
            SENSITIVE_DIRECTORY_PERMISSIONS
            if directory_name in SENSITIVE_DIRECTORIES
            else DIRECTORY_PERMISSIONS
        )

        _ensure_directory(
            paths[directory_name],
            permissions,
        )

    logger.info(
        "Application storage initialised",
        extra={
            "storage_directory_count": len(STORAGE_DIRECTORIES),
        },
    )

    return paths


def validate_storage(
    paths: dict[str, Path] | None = None,
) -> None:
    """
    Validate storage directory existence and write access.

    Uses temporary probe files to verify actual filesystem
    permissions instead of relying solely on permission bits.
    """
    storage_paths = paths or get_storage_paths()

    required_paths = [
        storage_paths["root"],
        *(
            storage_paths[name]
            for name in STORAGE_DIRECTORIES
        ),
    ]

    for directory in required_paths:
        try:
            if not directory.exists():
                raise StorageError(
                    f"Required storage directory does not exist: {directory.name}"
                )

            if not directory.is_dir():
                raise StorageError(
                    f"Storage path is not a directory: {directory.name}"
                )

            probe_path = directory / (
                f".teleforward-write-test-{os.getpid()}"
            )

            file_descriptor = os.open(
                probe_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                FILE_PERMISSIONS,
            )

            os.close(file_descriptor)
            probe_path.unlink()

        except StorageError:
            raise

        except OSError as exc:
            raise StorageError(
                f"Storage directory is not accessible: {directory.name}"
            ) from exc

    logger.info("Application storage validation completed")


def get_storage_usage() -> dict[str, int]:
    """
    Return filesystem usage for the persistent data volume.

    Values are expressed in bytes.
    """
    root = get_data_directory()

    try:
        usage = os.statvfs(root)

        return {
            "total_bytes": usage.f_blocks * usage.f_frsize,
            "used_bytes": (
                usage.f_blocks - usage.f_bfree
            ) * usage.f_frsize,
            "available_bytes": usage.f_bavail * usage.f_frsize,
        }

    except OSError as exc:
        raise StorageError(
            "Unable to retrieve storage usage information"
        ) from exc


def get_storage_directory_size(
    directory: Path,
) -> int:
    """
    Calculate the total size of files in a storage directory.

    Symbolic links are not followed.
    """
    if not directory.exists() or not directory.is_dir():
        raise StorageError(
            "Storage directory does not exist or is invalid"
        )

    total_size = 0

    try:
        for entry in directory.rglob("*"):
            if entry.is_symlink() or not entry.is_file():
                continue

            try:
                total_size += entry.stat(
                    follow_symlinks=False
                ).st_size
            except OSError:
                logger.warning(
                    "Unable to inspect a storage file",
                    extra={"filename": entry.name},
                )

        return total_size

    except OSError as exc:
        raise StorageError(
            "Unable to calculate storage directory size"
        ) from exc
