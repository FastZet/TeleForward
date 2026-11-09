
"""
TeleForward application lifecycle management.

Responsible for:
- Application startup and shutdown.
- Structured logging initialisation.
- Persistent storage initialisation and validation.
- Secure bootstrap of application secrets.
- Database initialisation and disposal.
- Application readiness management.
- Lifecycle event publication.
"""

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from cryptography.fernet import Fernet
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.events import (
    ApplicationEvent,
    EventNames,
    event_dispatcher,
)
from app.core.logging import configure_logging
from app.core.paths import (
    initialise_storage,
    validate_storage,
)
from app.database.engine import get_database_engine
from app.database.init import (
    initialise_database,
    shutdown_database,
)
from app.database.session import get_session_factory


logger = logging.getLogger(__name__)


_SECRET_FILENAMES = {
    "secret_key": "secret_key",
    "encryption_key": "encryption_key",
    "jwt_secret_key": "jwt_secret_key",
}


def _generate_secret(setting_name: str) -> str:
    """Generate a cryptographically secure secret."""
    if setting_name == "encryption_key":
        return Fernet.generate_key().decode("ascii")

    return secrets.token_urlsafe(64)


def _read_or_create_secret(
    directory: Path,
    setting_name: str,
    filename: str,
) -> str:
    """
    Load an existing persistent secret or create one securely.

    Files are created with restrictive permissions. Exclusive
    creation prevents concurrent application instances from
    overwriting an already-created secret.
    """
    secret_path = directory / filename

    if secret_path.exists():
        if not secret_path.is_file():
            raise RuntimeError(
                f"Security secret path is not a regular file: {filename}"
            )

        secret = secret_path.read_text(encoding="utf-8").strip()

        if not secret:
            raise RuntimeError(
                f"Security secret file is empty: {filename}"
            )

        return secret

    secret = _generate_secret(setting_name)

    try:
        file_descriptor = os.open(
            secret_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        # Another process created the secret concurrently.
        return _read_or_create_secret(
            directory,
            setting_name,
            filename,
        )

    try:
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
        ) as secret_file:
            secret_file.write(secret)
            secret_file.write("\n")
            secret_file.flush()
            os.fsync(secret_file.fileno())
    except Exception:
        secret_path.unlink(missing_ok=True)
        raise

    logger.info(
        "Generated and persisted application security secret",
        extra={"secret_type": setting_name},
    )

    return secret


def initialise_application_secrets() -> None:
    """
    Initialise all required application security secrets.

    Explicit environment configuration takes precedence.
    Missing secrets are generated and persisted in the data
    directory so that they remain stable across restarts.
    """
    settings = get_settings()

    secrets_directory = Path(settings.data_dir) / "secrets"
    secrets_directory.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )

    try:
        secrets_directory.chmod(0o700)
    except OSError:
        logger.warning(
            "Unable to enforce restrictive permissions on secrets directory"
        )

    for setting_name, filename in _SECRET_FILENAMES.items():
        configured_secret = getattr(settings, setting_name, None)

        if configured_secret:
            continue

        generated_secret = _read_or_create_secret(
            directory=secrets_directory,
            setting_name=setting_name,
            filename=filename,
        )

        # Pydantic Settings instances are mutable by default.
        # Keep the resolved value available to application services.
        setattr(settings, setting_name, generated_secret)


async def _publish_event(
    event_name: EventNames,
    data: dict[str, Any] | None = None,
) -> None:
    """Publish an application lifecycle event."""
    await event_dispatcher.publish(
        ApplicationEvent(
            name=event_name,
            data=data or {},
        )
    )


@asynccontextmanager
async def application_lifespan(
    app: FastAPI,
) -> AsyncIterator[None]:
    """
    Manage the complete FastAPI application lifecycle.

    Readiness is enabled only after all mandatory startup
    operations have completed successfully.
    """
    app.state.ready = False

    database_initialised = False

    try:
        # Load application configuration.
        settings = get_settings()

        # Initialise structured logging before other startup work.
        configure_logging(settings)

        logger.info("Starting TeleForward")

        # Prepare persistent storage.
        storage_paths = initialise_storage()
        validate_storage(storage_paths)

        app.state.storage_paths = storage_paths

        # Generate or load persistent security secrets.
        initialise_application_secrets()

        # Initialise database connectivity and migrations.
        await initialise_database()
        database_initialised = True

        # Expose database resources to application dependencies.
        app.state.database_engine = get_database_engine()
        app.state.database_session_factory = get_session_factory()

        # Notify application event subscribers.
        await _publish_event(
            EventNames.APPLICATION_STARTED,
            {
                "application": "TeleForward",
                "version": "0.1.0",
            },
        )

        # Application is ready only after mandatory startup succeeds.
        app.state.ready = True

        logger.info("TeleForward startup completed successfully")

        yield

    except Exception:
        app.state.ready = False

        logger.exception("TeleForward startup or runtime lifecycle failed")

        raise

    finally:
        # Prevent new requests from being treated as ready.
        app.state.ready = False

        logger.info("Stopping TeleForward")

        try:
            await _publish_event(
                EventNames.APPLICATION_STOPPING,
                {"application": "TeleForward"},
            )
        except Exception:
            logger.exception(
                "Failed to publish application shutdown event"
            )

        if database_initialised:
            try:
                await shutdown_database()
            except Exception:
                logger.exception(
                    "Database shutdown encountered an error"
                )

        app.state.database_engine = None
        app.state.database_session_factory = None

        logger.info("TeleForward shutdown completed")
