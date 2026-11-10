"""
Telegram health monitoring service.

Supports:
- Checking Telegram client connection state.
- Checking account authorisation.
- Testing Telegram API responsiveness.
- Measuring API response latency.
- Reporting structured health information.
- Handling Telegram rate limits and connection failures.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

import structlog
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from app.services.telegram.client import TelegramClientManager


logger = structlog.get_logger(__name__)


class TelegramHealthStatus(StrEnum):
    """Overall Telegram account health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNAUTHORISED = "unauthorised"


@dataclass(frozen=True, slots=True)
class TelegramHealthCheck:
    """Result of an individual health check."""

    name: str
    successful: bool
    latency_ms: float | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramHealthReport:
    """Complete health report for a Telegram account."""

    account_id: int
    status: TelegramHealthStatus
    connected: bool
    authorised: bool
    responsive: bool
    user_id: int | None
    username: str | None
    latency_ms: float | None
    checked_at: datetime
    checks: tuple[TelegramHealthCheck, ...]
    error: str | None = None
    retry_after_seconds: int | None = None


class TelegramHealthService:
    """Monitor Telegram account connectivity and health."""

    def __init__(
        self,
        client_manager: TelegramClientManager,
        *,
        latency_warning_ms: float = 3000.0,
    ) -> None:
        if latency_warning_ms <= 0:
            raise ValueError(
                "latency_warning_ms must be positive."
            )

        self.client_manager = client_manager
        self.latency_warning_ms = latency_warning_ms

    async def check_account(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> TelegramHealthReport:
        """Run a health check for one Telegram account."""
        if account_id <= 0:
            raise ValueError(
                "account_id must be positive."
            )

        checked_at = datetime.now(timezone.utc)
        checks: list[TelegramHealthCheck] = []

        try:
            client = await self.client_manager.get_client(
                account_id=account_id,
                api_id=api_id,
                api_hash=api_hash,
                connect=True,
            )

        except FloodWaitError as exc:
            return self._build_report(
                account_id=account_id,
                status=TelegramHealthStatus.DEGRADED,
                connected=False,
                authorised=False,
                responsive=False,
                checked_at=checked_at,
                checks=(
                    TelegramHealthCheck(
                        name="client_initialisation",
                        successful=False,
                        error="flood_wait",
                    ),
                ),
                error="Telegram rate limit encountered.",
                retry_after_seconds=exc.seconds,
            )

        except Exception as exc:
            logger.warning(
                "telegram_health_client_initialisation_failed",
                account_id=account_id,
                error_type=type(exc).__name__,
            )

            return self._build_report(
                account_id=account_id,
                status=TelegramHealthStatus.UNAVAILABLE,
                connected=False,
                authorised=False,
                responsive=False,
                checked_at=checked_at,
                checks=(
                    TelegramHealthCheck(
                        name="client_initialisation",
                        successful=False,
                        error=type(exc).__name__,
                    ),
                ),
                error="Telegram client could not be initialised.",
            )

        connected = client.is_connected()

        checks.append(
            TelegramHealthCheck(
                name="connection",
                successful=connected,
            )
        )

        if not connected:
            return self._build_report(
                account_id=account_id,
                status=TelegramHealthStatus.UNAVAILABLE,
                connected=False,
                authorised=False,
                responsive=False,
                checked_at=checked_at,
                checks=tuple(checks),
                error="Telegram client is disconnected.",
            )

        try:
            auth_started = time.perf_counter()

            authorised = await client.is_user_authorized()

            auth_latency = (
                time.perf_counter() - auth_started
            ) * 1000

            checks.append(
                TelegramHealthCheck(
                    name="authorisation",
                    successful=authorised,
                    latency_ms=round(auth_latency, 2),
                )
            )

        except FloodWaitError as exc:
            checks.append(
                TelegramHealthCheck(
                    name="authorisation",
                    successful=False,
                    error="flood_wait",
                )
            )

            return self._build_report(
                account_id=account_id,
                status=TelegramHealthStatus.DEGRADED,
                connected=connected,
                authorised=False,
                responsive=False,
                checked_at=checked_at,
                checks=tuple(checks),
                error="Telegram rate limit encountered.",
                retry_after_seconds=exc.seconds,
            )

        except Exception as exc:
            checks.append(
                TelegramHealthCheck(
                    name="authorisation",
                    successful=False,
                    error=type(exc).__name__,
                )
            )

            return self._build_report(
                account_id=account_id,
                status=TelegramHealthStatus.DEGRADED,
                connected=connected,
                authorised=False,
                responsive=False,
                checked_at=checked_at,
                checks=tuple(checks),
                error="Telegram authorisation check failed.",
            )

        if not authorised:
            return self._build_report(
                account_id=account_id,
                status=TelegramHealthStatus.UNAUTHORISED,
                connected=connected,
                authorised=False,
                responsive=False,
                checked_at=checked_at,
                checks=tuple(checks),
                error="Telegram account requires authentication.",
            )

        try:
            api_started = time.perf_counter()

            me = await client.get_me()

            api_latency = (
                time.perf_counter() - api_started
            ) * 1000

            responsive = me is not None

            checks.append(
                TelegramHealthCheck(
                    name="api_responsiveness",
                    successful=responsive,
                    latency_ms=round(api_latency, 2),
                )
            )

        except FloodWaitError as exc:
            checks.append(
                TelegramHealthCheck(
                    name="api_responsiveness",
                    successful=False,
                    error="flood_wait",
                )
            )

            return self._build_report(
                account_id=account_id,
                status=TelegramHealthStatus.DEGRADED,
                connected=connected,
                authorised=True,
                responsive=False,
                checked_at=checked_at,
                checks=tuple(checks),
                error="Telegram rate limit encountered.",
                retry_after_seconds=exc.seconds,
            )

        except Exception as exc:
            checks.append(
                TelegramHealthCheck(
                    name="api_responsiveness",
                    successful=False,
                    error=type(exc).__name__,
                )
            )

            return self._build_report(
                account_id=account_id,
                status=TelegramHealthStatus.DEGRADED,
                connected=connected,
                authorised=True,
                responsive=False,
                checked_at=checked_at,
                checks=tuple(checks),
                error="Telegram API responsiveness check failed.",
            )

        if not responsive:
            return self._build_report(
                account_id=account_id,
                status=TelegramHealthStatus.DEGRADED,
                connected=connected,
                authorised=True,
                responsive=False,
                checked_at=checked_at,
                checks=tuple(checks),
                error="Telegram did not return account information.",
            )

        status = (
            TelegramHealthStatus.DEGRADED
            if api_latency > self.latency_warning_ms
            else TelegramHealthStatus.HEALTHY
        )

        report = self._build_report(
            account_id=account_id,
            status=status,
            connected=connected,
            authorised=True,
            responsive=True,
            user_id=me.id,
            username=getattr(me, "username", None),
            latency_ms=api_latency,
            checked_at=checked_at,
            checks=tuple(checks),
        )

        logger.info(
            "telegram_account_health_checked",
            account_id=account_id,
            status=report.status.value,
            latency_ms=report.latency_ms,
        )

        return report

    async def check_connection(
        self,
        account_id: int,
        api_id: int,
        api_hash: str,
    ) -> bool:
        """Return whether the Telegram account is healthy."""
        report = await self.check_account(
            account_id,
            api_id,
            api_hash,
        )

        return report.status == TelegramHealthStatus.HEALTHY

    @staticmethod
    def _build_report(
        *,
        account_id: int,
        status: TelegramHealthStatus,
        connected: bool,
        authorised: bool,
        responsive: bool,
        checked_at: datetime,
        checks: tuple[TelegramHealthCheck, ...],
        user_id: int | None = None,
        username: str | None = None,
        latency_ms: float | None = None,
        error: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> TelegramHealthReport:
        """Construct a normalised health report."""
        return TelegramHealthReport(
            account_id=account_id,
            status=status,
            connected=connected,
            authorised=authorised,
            responsive=responsive,
            user_id=user_id,
            username=username,
            latency_ms=(
                round(latency_ms, 2)
                if latency_ms is not None
                else None
            ),
            checked_at=checked_at,
            checks=checks,
            error=error,
            retry_after_seconds=retry_after_seconds,
        )
