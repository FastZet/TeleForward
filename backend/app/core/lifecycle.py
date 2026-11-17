
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
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import select

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
from app.core.security import decrypt_value, encrypt_value
from app.database.engine import get_database_engine
from app.database.init import (
    initialise_database,
    shutdown_database,
)
from app.database.session import get_session_factory
from app.models.chat import TelegramChat
from app.models.forwarding_rule import ForwardingRule
from app.models.telegram_account import TelegramAccount
from app.models.processing_queue import QueueJobType
from app.services.processing_queue_handlers import ProcessingQueueHandlers
from app.services.processing_queue_worker import ProcessingQueueWorker
from app.services.telegram.client import TelegramClientManager
from app.services.telegram.credentials import TelegramCredentialsService
from app.services.telegram.auth import TelegramAuthenticationService
from app.services.telegram.ingestion import TelegramUpdateIngestionService
from app.services.telegram.updates import TelegramUpdatesService


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


async def _start_background_processing(
    app: FastAPI,
    storage_paths: dict[str, Path],
) -> None:
    """Start the durable forwarding worker and available Telegram listeners."""
    session_factory = get_session_factory()
    client_manager = TelegramClientManager(storage_paths["sessions"])
    handlers = ProcessingQueueHandlers(
        session_factory,
        client_manager,
        album_storage_dir=storage_paths["temporary"],
    )
    worker = ProcessingQueueWorker(
        session_factory,
        worker_id=f"{os.getpid()}-{secrets.token_hex(8)}",
        handlers={
            QueueJobType.FORWARD_MESSAGE: handlers.forward_message,
            QueueJobType.SYNC_EDIT: handlers.sync_message_edit,
            QueueJobType.SYNC_DELETE: handlers.sync_message_delete,
        },
    )
    updates = TelegramUpdatesService(client_manager)
    ingestion = TelegramUpdateIngestionService(session_factory)

    app.state.telegram_client_manager = client_manager
    app.state.telegram_updates_service = updates
    app.state.telegram_auth_service = TelegramAuthenticationService(client_manager)
    app.state.telegram_update_ingestion = ingestion
    app.state.processing_queue_worker = worker
    app.state.processing_queue_task = asyncio.create_task(
        worker.run(),
        name="teleforward-processing-queue",
    )

    try:
        async with session_factory() as session:
            credentials = await TelegramCredentialsService(session).get_credentials()
            if credentials is None:
                logger.info("Telegram listeners not started: API credentials are not configured")
                return

            accounts = (
                await session.scalars(
                    select(TelegramAccount).where(TelegramAccount.is_enabled.is_(True))
                )
            ).all()
            for account in accounts:
                if account.session_data_encrypted:
                    try:
                        await client_manager.get_client(
                            account.id,
                            credentials.api_id,
                            credentials.api_hash,
                            connect=False,
                            session_string=decrypt_value(
                                account.session_data_encrypted
                            ),
                        )
                    except Exception as exc:
                        logger.warning(
                            "Stored Telegram session could not be restored",
                            extra={
                                "account_id": account.id,
                                "error_type": type(exc).__name__,
                            },
                        )
                        continue
                chat_ids = list(
                    (
                        await session.scalars(
                            select(TelegramChat.telegram_chat_id)
                            .join(
                                ForwardingRule,
                                ForwardingRule.source_chat_id == TelegramChat.id,
                            )
                            .where(
                                ForwardingRule.telegram_account_id == account.id,
                                ForwardingRule.is_enabled.is_(True),
                                TelegramChat.is_accessible.is_(True),
                            )
                            .distinct()
                        )
                    ).all()
                )
                if not chat_ids:
                    continue
                try:
                    await updates.register_handlers(
                        account.id,
                        credentials.api_id,
                        credentials.api_hash,
                        ingestion.handle_update,
                        chats=chat_ids,
                    )
                except Exception as exc:
                    # A disconnected/unavailable account must not prevent the
                    # API and queue from starting for other accounts.
                    logger.warning(
                        "Telegram update listener unavailable",
                        extra={
                            "account_id": account.id,
                            "error_type": type(exc).__name__,
                        },
                    )
    except Exception:
        worker.stop()
        app.state.processing_queue_task.cancel()
        await asyncio.gather(app.state.processing_queue_task, return_exceptions=True)
        await client_manager.disconnect_all()
        app.state.processing_queue_task = None
        app.state.processing_queue_worker = None
        app.state.telegram_updates_service = None
        app.state.telegram_auth_service = None
        app.state.telegram_update_ingestion = None
        app.state.telegram_client_manager = None
        raise


async def _stop_background_processing(app: FastAPI) -> None:
    """Stop queue work before disconnecting Telegram clients."""
    updates = getattr(app.state, "telegram_updates_service", None)
    worker = getattr(app.state, "processing_queue_worker", None)
    task = getattr(app.state, "processing_queue_task", None)
    client_manager = getattr(app.state, "telegram_client_manager", None)

    try:
        if updates is not None:
            try:
                await updates.unregister_all()
            except Exception:
                logger.exception("Telegram update-handler shutdown failed")
        if worker is not None:
            worker.stop()
        if task is not None:
            try:
                await task
            except Exception:
                logger.exception("Processing queue worker stopped with an error")

        if client_manager is not None:
            session_factory = getattr(app.state, "database_session_factory", None)
            if session_factory is not None:
                try:
                    async with session_factory() as session:
                        account_ids = client_manager.get_managed_account_ids()
                        accounts = list((await session.scalars(
                            select(TelegramAccount).where(
                                TelegramAccount.id.in_(account_ids)
                            )
                        )).all()) if account_ids else []
                        for account in accounts:
                            client = client_manager.get_managed_client(account.id)
                            if client is None or not client.is_connected():
                                continue
                            try:
                                if not await client.is_user_authorized():
                                    continue
                                session_string = await client_manager.export_session(account.id)
                                if session_string:
                                    account.session_data_encrypted = encrypt_value(session_string)
                            except Exception as exc:
                                logger.warning(
                                    "Telegram session persistence failed during shutdown",
                                    extra={
                                        "account_id": account.id,
                                        "error_type": type(exc).__name__,
                                    },
                                )
                        await session.commit()
                except Exception:
                    logger.exception("Could not persist Telegram sessions during shutdown")
            await client_manager.disconnect_all()
    finally:
        app.state.processing_queue_task = None
        app.state.processing_queue_worker = None
        app.state.telegram_updates_service = None
        app.state.telegram_auth_service = None
        app.state.telegram_update_ingestion = None
        app.state.telegram_client_manager = None


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

        await _start_background_processing(app, storage_paths)

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

        try:
            await _stop_background_processing(app)
        except Exception:
            logger.exception("Background processing shutdown encountered an error")

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

