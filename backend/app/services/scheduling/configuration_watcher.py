"""File watcher for scheduled-task configuration changes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.services.scheduling.configuration_service import (
    ConfigurationService,
)


logger = logging.getLogger(__name__)

ReloadCallback = Callable[
    [dict[str, Any]],
    Awaitable[None] | None,
]


class ConfigurationWatcher:
    """Poll a configuration file and reload it when modified."""

    def __init__(
        self,
        service: ConfigurationService,
        path: str | Path,
        *,
        poll_interval_seconds: float = 2.0,
        debounce_seconds: float = 1.0,
        on_reload: ReloadCallback | None = None,
    ) -> None:
        if not isinstance(service, ConfigurationService):
            raise TypeError(
                "service must be a ConfigurationService instance"
            )

        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or poll_interval_seconds <= 0
        ):
            raise ValueError(
                "poll_interval_seconds must be positive"
            )

        if (
            isinstance(debounce_seconds, bool)
            or not isinstance(debounce_seconds, (int, float))
            or debounce_seconds < 0
        ):
            raise ValueError(
                "debounce_seconds must be non-negative"
            )

        if on_reload is not None and not callable(on_reload):
            raise TypeError("on_reload must be callable")

        self._service = service
        self._path = Path(path).expanduser()
        self._poll_interval = float(poll_interval_seconds)
        self._debounce = float(debounce_seconds)
        self._on_reload = on_reload

        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._reload_lock = asyncio.Lock()

        self._last_signature: tuple[int, int] | None = None

    @property
    def is_running(self) -> bool:
        """Whether the watcher background task is running."""

        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start monitoring the configuration file."""

        if self.is_running:
            return

        if not self._path.is_file():
            raise FileNotFoundError(
                f"Configuration file does not exist: {self._path}"
            )

        self._last_signature = self._get_signature()
        self._stop_event.clear()

        self._task = asyncio.create_task(
            self._watch_loop(),
            name="teleforward-configuration-watcher",
        )

        logger.info(
            "Configuration watcher started for %s",
            self._path,
        )

    async def stop(self) -> None:
        """Stop monitoring and wait for the watcher task to finish."""

        task = self._task

        if task is None:
            return

        self._stop_event.set()

        try:
            await task
        finally:
            self._task = None

        logger.info(
            "Configuration watcher stopped for %s",
            self._path,
        )

    async def reload_now(self) -> dict[str, Any]:
        """Reload and synchronise the configuration immediately."""

        async with self._reload_lock:
            configuration = self._service.load(self._path)
            result = await self._service.synchronize()

            status = {
                "success": result.success,
                "source": str(self._path),
                "loaded_tasks": len(configuration),
                "created": list(result.created),
                "updated": list(result.updated),
                "deleted": list(result.deleted),
                "failures": [
                    {
                        "operation": failure.operation,
                        "target": failure.target,
                        "error_type": failure.error_type,
                        "message": failure.message,
                    }
                    for failure in result.failures
                ],
            }

            if self._on_reload is not None:
                callback_result = self._on_reload(status)

                if asyncio.iscoroutine(callback_result):
                    await callback_result

            self._last_signature = self._get_signature()

            return status

    async def _watch_loop(self) -> None:
        """Poll the file until stopped."""

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval,
                )
                continue
            except asyncio.TimeoutError:
                pass

            try:
                signature = self._get_signature()
            except FileNotFoundError:
                logger.warning(
                    "Configuration file temporarily unavailable: %s",
                    self._path,
                )
                continue
            except OSError:
                logger.exception(
                    "Unable to inspect configuration file: %s",
                    self._path,
                )
                continue

            if signature == self._last_signature:
                continue

            if self._debounce:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._debounce,
                    )
                    continue
                except asyncio.TimeoutError:
                    pass

            try:
                await self.reload_now()
                logger.info(
                    "Configuration successfully reloaded from %s",
                    self._path,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Configuration reload failed; retaining the "
                    "previous active configuration"
                )

                try:
                    self._last_signature = self._get_signature()
                except OSError:
                    pass

    def _get_signature(self) -> tuple[int, int]:
        """Return modification time and file size."""

        stat = self._path.stat()

        if not self._path.is_file():
            raise FileNotFoundError(self._path)

        return stat.st_mtime_ns, stat.st_size
