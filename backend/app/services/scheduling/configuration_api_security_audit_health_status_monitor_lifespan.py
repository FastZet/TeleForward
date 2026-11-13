
"""Application lifespan integration for the security-audit health monitor."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.services.scheduling.configuration_api_security_audit_health_status_monitor_integration import (
    SecurityAuditHealthStatusMonitorIntegrationError,
    get_configuration_api_security_audit_health_status_monitor,
)


logger = logging.getLogger(__name__)


class SecurityAuditHealthStatusMonitorLifespanError(RuntimeError):
    """Raised when health-monitor lifespan operations fail."""


LifespanCallback = Callable[
    [FastAPI],
    Any,
]


def create_security_audit_health_status_monitor_lifespan(
    *,
    run_immediately: bool = True,
    cancel_running_check_on_shutdown: bool = False,
    before_start: LifespanCallback | None = None,
    after_start: LifespanCallback | None = None,
    before_shutdown: LifespanCallback | None = None,
    after_shutdown: LifespanCallback | None = None,
):
    """Create a FastAPI lifespan context manager for the monitor.

    The monitor must already be installed in app.state before startup.

    Optional callbacks can be synchronous or asynchronous. They are
    executed in this order:

        before_start
        monitor.start()
        after_start
        application runs
        before_shutdown
        monitor.stop()
        after_shutdown

    If startup fails after the monitor starts, the monitor is stopped
    before the startup exception propagates.
    """

    if not isinstance(run_immediately, bool):
        raise TypeError("run_immediately must be a boolean")

    if not isinstance(cancel_running_check_on_shutdown, bool):
        raise TypeError(
            "cancel_running_check_on_shutdown must be a boolean"
        )

    callbacks = (
        before_start,
        after_start,
        before_shutdown,
        after_shutdown,
    )

    if any(
        callback is not None and not callable(callback)
        for callback in callbacks
    ):
        raise TypeError("lifespan callbacks must be callable or None")

    async def invoke_callback(
        callback: LifespanCallback | None,
        app: FastAPI,
    ) -> None:
        if callback is None:
            return

        result = callback(app)

        if hasattr(result, "__await__"):
            await result

    @asynccontextmanager
    async def lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        try:
            monitor = (
                get_configuration_api_security_audit_health_status_monitor(
                    app
                )
            )

        except SecurityAuditHealthStatusMonitorIntegrationError as exc:
            raise SecurityAuditHealthStatusMonitorLifespanError(
                "Security-audit health monitor must be installed "
                "before application startup"
            ) from exc

        started = False

        try:
            await invoke_callback(before_start, app)

            await monitor.start(
                run_immediately=run_immediately,
            )

            started = True

            await invoke_callback(after_start, app)

            logger.info(
                "Security-audit health monitor started"
            )

            yield

        except BaseException:
            if started:
                try:
                    await monitor.stop(
                        cancel_running_check=(
                            cancel_running_check_on_shutdown
                        )
                    )
                except Exception:
                    logger.exception(
                        "Failed to stop health monitor after startup failure"
                    )

            raise

        else:
            try:
                await invoke_callback(before_shutdown, app)

            except Exception:
                logger.exception(
                    "Health-monitor before-shutdown callback failed"
                )

            finally:
                try:
                    await monitor.stop(
                        cancel_running_check=(
                            cancel_running_check_on_shutdown
                        )
                    )

                except Exception as exc:
                    logger.exception(
                        "Failed to stop security-audit health monitor"
                    )

                    raise SecurityAuditHealthStatusMonitorLifespanError(
                        "Failed to stop security-audit health monitor"
                    ) from exc

                logger.info(
                    "Security-audit health monitor stopped"
                )

                try:
                    await invoke_callback(after_shutdown, app)

                except Exception:
                    logger.exception(
                        "Health-monitor after-shutdown callback failed"
                    )

    return lifespan


__all__ = [
    "SecurityAuditHealthStatusMonitorLifespanError",
    "LifespanCallback",
    "create_security_audit_health_status_monitor_lifespan",
]
