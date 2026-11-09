
"""
TeleForward application lifecycle management.

Handles:
- Application logging configuration.
- Persistent cryptographic secret bootstrapping.
- Storage initialisation and validation.
- Database initialisation and shutdown.
- Application readiness management.
- Graceful startup and shutdown.
"""

import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from cryptography.fernet import Fernet
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.paths import initialise_storage, validate_storage
from app.database.engine import get_database_engine
from app.database.init import initialise_database, shutdown_database
from app.database.session import get_session_factory


logger = logging.getLogger(__name__)

SECRET_FILE_NAME = ".teleforward-secrets.json"

SECRET_KEYS = (
    "secret_key",
    "encryption_key",
    "jwt_secret_key",
)


def _generate_bootstrap_secrets() -> dict[str, str]:
    """Generate cryptographically secure application secrets."""
    return {
        "secret_key": secrets.token_urlsafe(48),
        "encryption_key": Fernet.generate_key().decode("ascii"),
        "jwt_secret_key": secrets.token_urlsafe(48),
    }


def _read_secret_file(path: Path) -> dict[str, str]:
    """Read and validate the persistent secret file."""
    try:
        with path.open("r", encoding="utf-8") as file:
            stored_secrets = json.load(file)

    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Unable to read the persistent application secrets file."
        ) from exc

    if not isinstance(stored_secrets, dict):
        raise RuntimeError(
            "The persistent application secrets file is invalid."
        )

    for key in SECRET_KEYS:
        value = stored_secrets.get(key)

        if not isinstance(value, str) or not value:
            raise RuntimeError(
                f"The persistent secrets file is missing {key}."
            )

    return stored_secrets


def _load_or_create_secret_file(data_dir: Path) -> dict[str, str]:
    """
    Load persistent secrets or create them on first startup.

    The file is created atomically with restrictive permissions.
    """
    path = data_dir / SECRET_FILE_NAME

    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(
                "The application secrets path is not a regular file."
            )

        if os.name == "posix":
            permissions = path.stat().st_mode & 0o777

            if permissions & 0o077:
                raise RuntimeError(
                    "Application secrets file permissions are too "
                    "permissive. Set them to 600."
                )

        return _read_secret_file(path)

    generated_secrets = _generate_bootstrap_secrets()

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        file_descriptor = os.open(
            path,
            flags,
            0o600,
        )

    except FileExistsError:
        # Another process may have created the file concurrently.
        return _read_secret_file(path)

    try:
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                generated_secrets,
                file,
                indent=2,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception(
                "Unable to remove an incomplete secrets file."
            )
        raise

    return generated_secrets


def initialise_application_secrets() -> None:
    """
    Ensure that all cryptographic secrets are available.

    Explicit environment configuration takes precedence over
    persistent bootstrap secrets.
    """
    settings = get_settings()

    data_dir = Path(settings.data_dir)
    stored_secrets = _load_or_create_secret_file(data_dir)

    for key in SECRET_KEYS:
        configured_value = getattr(settings, key, None)

        if configured_value:
            continue

        setattr(
            settings,
            key,
            stored_secrets[key],
        )

    logger.info(
        "Application cryptographic secrets are available."
    )


async def _shutdown_services(app: FastAPI) -> None:
    """
    Stop application services in dependency-safe order.

    Additional Telegram, scheduler and worker shutdown operations
    will be registered here as those services are implemented.
    """
    shutdown_errors: list[str] = []

    # Stop background workers before disposing database resources.
    workers = getattr(app.state, "workers", [])

    for worker in reversed(workers):
        try:
            await worker.stop()
        except Exception:
            logger.exception("Unable to stop a background worker.")
            shutdown_errors.append("background worker")

    # Stop the scheduler if it has been initialised.
    scheduler = getattr(app.state, "scheduler", None)

    if scheduler is not None:
        try:
            await scheduler.shutdown()
        except Exception:
            logger.exception("Unable to shut down the scheduler.")
            shutdown_errors.append("scheduler")

    # Disconnect Telegram clients.
    telegram_manager = getattr(
        app.state,
        "telegram_manager",
        None,
    )

    if telegram_manager is not None:
        try:
            await telegram_manager.disconnect_all()
        except Exception:
            logger.exception(
                "Unable to disconnect Telegram clients."
            )
            shutdown_errors.append("Telegram clients")

    # Database resources must remain available until dependent
    # workers and services have stopped.
    try:
        await shutdown_database()
    except Exception:
        logger.exception("Unable to shut down the database.")
        shutdown_errors.append("database")

    if shutdown_errors:
        logger.error(
            "Application shutdown completed with errors: %s",
            ", ".join(shutdown_errors),
        )


@asynccontextmanager
async def application_lifespan(
    app: FastAPI,
) -> AsyncIterator[None]:
    """
    Manage application startup and shutdown.

    The application becomes ready only after configuration,
    storage and database initialisation have succeeded.
    """
    settings = get_settings()

    app.state.ready = False

    configure_logging(settings)

    logger.info(
        "Starting %s in %s mode.",
        "TeleForward",
        settings.environment,
    )

    try:
        # Initialise persistent storage directories.
        initialise_storage()
        validate_storage()

        # Generate or load secrets after the data directory exists.
        initialise_application_secrets()

        # Initialise the database and apply pending Alembic migrations.
        await initialise_database(
            apply_migrations=True,
            create_schema=False,
        )

        # Expose database resources to application dependencies.
        app.state.database_engine = get_database_engine()
        app.state.database_session_factory = get_session_factory()

        # Initialise service registries for later integration.
        if not hasattr(app.state, "workers"):
            app.state.workers = []

        app.state.scheduler = getattr(
            app.state,
            "scheduler",
            None,
        )

        app.state.telegram_manager = getattr(
            app.state,
            "telegram_manager",
            None,
        )

        # All mandatory startup operations have succeeded.
        app.state.ready = True

        logger.info("TeleForward startup completed successfully.")

        yield

    except Exception:
        app.state.ready = False
        logger.exception("TeleForward startup failed.")

        # Clean up partially initialised resources.
        await _shutdown_services(app)
        raise

    finally:
        # Readiness must be withdrawn before shutdown begins.
        app.state.ready = False

        logger.info("TeleForward is shutting down.")

        await _shutdown_services(app)

        logger.info("TeleForward shutdown completed.")
