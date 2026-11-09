
"""
TeleForward internal application event system.

Provides an asynchronous, in-process event dispatcher for
decoupled communication between application components.
"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog


logger = structlog.get_logger(__name__)

EventHandler = Callable[["ApplicationEvent"], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    """
    Immutable application event.

    Attributes:
        name: Event identifier.
        payload: Event-specific data.
        event_id: Unique event identifier.
        occurred_at: UTC event creation timestamp.
    """

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventDispatcher:
    """
    Asynchronous in-process event dispatcher.

    Handlers are registered against event names and invoked
    asynchronously when matching events are published.

    Handler failures are logged and isolated so that one
    subscriber does not prevent other subscribers from running.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(
        self,
        event_name: str,
        handler: EventHandler,
    ) -> None:
        """
        Register an asynchronous event handler.
        """
        if not event_name.strip():
            raise ValueError("Event name cannot be empty.")

        async with self._lock:
            if handler not in self._handlers[event_name]:
                self._handlers[event_name].append(handler)

    async def unsubscribe(
        self,
        event_name: str,
        handler: EventHandler,
    ) -> None:
        """
        Remove a previously registered event handler.
        """
        async with self._lock:
            handlers = self._handlers.get(event_name)

            if not handlers:
                return

            if handler in handlers:
                handlers.remove(handler)

            if not handlers:
                self._handlers.pop(event_name, None)

    async def publish(
        self,
        event_name: str,
        payload: dict[str, Any] | None = None,
    ) -> ApplicationEvent:
        """
        Publish an event to all registered subscribers.

        Subscribers are executed concurrently. Exceptions
        raised by individual subscribers are logged without
        preventing other subscribers from executing.

        Returns:
            The published ApplicationEvent.
        """
        if not event_name.strip():
            raise ValueError("Event name cannot be empty.")

        event = ApplicationEvent(
            name=event_name,
            payload=payload or {},
        )

        async with self._lock:
            handlers = tuple(self._handlers.get(event_name, ()))

        if not handlers:
            logger.debug(
                "application_event_published_without_subscribers",
                event_name=event_name,
                event_id=event.event_id,
            )
            return event

        results = await asyncio.gather(
            *(self._execute_handler(handler, event) for handler in handlers),
            return_exceptions=True,
        )

        failed_handlers = sum(
            isinstance(result, BaseException)
            for result in results
        )

        logger.info(
            "application_event_published",
            event_name=event_name,
            event_id=event.event_id,
            subscriber_count=len(handlers),
            failed_handlers=failed_handlers,
        )

        return event

    async def _execute_handler(
        self,
        handler: EventHandler,
        event: ApplicationEvent,
    ) -> None:
        """
        Execute an individual event handler safely.
        """
        try:
            await handler(event)

        except Exception:
            logger.exception(
                "application_event_handler_failed",
                event_name=event.name,
                event_id=event.event_id,
                handler=getattr(
                    handler,
                    "__qualname__",
                    repr(handler),
                ),
            )


# Shared dispatcher instance for the application.
event_dispatcher = EventDispatcher()


# ============================================================
# Standard application event names
# ============================================================

class EventNames:
    """Central registry of application event identifiers."""

    # Telegram accounts
    TELEGRAM_ACCOUNT_CONNECTED = "telegram.account.connected"
    TELEGRAM_ACCOUNT_DISCONNECTED = "telegram.account.disconnected"
    TELEGRAM_ACCOUNT_AUTHENTICATION_FAILED = (
        "telegram.account.authentication_failed"
    )

    # Forwarding rules
    FORWARDING_RULE_CREATED = "forwarding.rule.created"
    FORWARDING_RULE_UPDATED = "forwarding.rule.updated"
    FORWARDING_RULE_DISABLED = "forwarding.rule.disabled"

    # Message processing
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_FORWARDED = "message.forwarded"
    MESSAGE_FORWARD_FAILED = "message.forward.failed"
    MESSAGE_SKIPPED = "message.skipped"

    # Scheduling
    SCHEDULED_TASK_STARTED = "scheduler.task.started"
    SCHEDULED_TASK_COMPLETED = "scheduler.task.completed"
    SCHEDULED_TASK_FAILED = "scheduler.task.failed"

    # Workers
    WORKER_STARTED = "worker.started"
    WORKER_STOPPED = "worker.stopped"
    WORKER_FAILED = "worker.failed"

    # Application lifecycle
    APPLICATION_STARTED = "application.started"
    APPLICATION_STOPPING = "application.stopping"
