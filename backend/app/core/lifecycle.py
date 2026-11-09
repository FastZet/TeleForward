
"""
TeleForward application lifecycle management.

Coordinates startup and shutdown operations, including
logging configuration, persistent storage initialisation,
configuration validation and application events.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.events import EventNames, event_dispatcher
from app.core.logging import configure_logging
from app.core.paths import initialise_storage, validate_storage


logger = structlog.get_logger(__name__)


def validate_application_configuration() -> None:
    """
    Validate essential production configuration.

    Raises:
        RuntimeError: If required production settings are missing.
    """
    settings = get_settings()

    if settings.is_production:
        if not settings.secret_key:
            raise RuntimeError(
                "TELEFORWARD_SECRET_KEY must be configured in production."
            )

        if not settings.encryption_key:
            raise RuntimeError(
                "TELEFORWARD_ENCRYPTION_KEY must be configured in production."
            )

        if not settings.jwt_secret_key:
            raise RuntimeError(
                "TELEFORWARD_JWT_SECRET_KEY must be configured in production."
            )


@asynccontextmanager
async def application_lifespan(
    app: FastAPI,
) -> AsyncIterator[None]:
    """
    Manage the FastAPI application's lifespan.

    Startup:
        1. Configure structured logging.
        2. Validate application configuration.
        3. Initialise persistent storage.
        4. Validate storage availability.
        5. Publish the application-started event.

    Shutdown:
        1. Publish the application-stopping event.
        2. Allow registered shutdown handlers to execute.

    Database engines, Telegram clients, schedulers and workers
    will be integrated into this lifecycle as their respective
    infrastructure modules are implemented.
    """
    configure_logging()

    settings = get_settings()

    logger.info(
        "application_starting",
        application=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )

    try:
        validate_application_configuration()

        storage_paths = initialise_storage()
        validate_storage()

        app.state.storage_paths = storage_paths

        logger.info(
            "application_storage_initialised",
            storage_directory=str(storage_paths.root),
        )

        await event_dispatcher.publish(
            EventNames.APPLICATION_STARTED,
            {
                "application": settings.app_name,
                "version": settings.app_version,
                "environment": settings.environment,
            },
        )

        logger.info("application_started")

        yield

    except Exception:
        logger.exception("application_lifecycle_failed")
        raise

    finally:
        logger.info("application_shutdown_started")

        try:
            await event_dispatcher.publish(
                EventNames.APPLICATION_STOPPING,
                {
                    "application": settings.app_name,
                },
            )

        except Exception:
            logger.exception("application_shutdown_handler_failed")

        logger.info("application_shutdown_completed")
