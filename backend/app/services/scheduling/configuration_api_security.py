"""Security utilities for scheduling configuration APIs."""

from __future__ import annotations

import asyncio
import logging
import time

from collections import defaultdict
from dataclasses import dataclass, field
from fastapi import HTTPException, Request, status

from app.services.scheduling.configuration_permissions import (
    ConfigurationPrincipal,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Request rate-limit policy."""

    max_requests: int = 60
    window_seconds: float = 60.0
    max_tracked_keys: int = 10_000

    def __post_init__(self) -> None:
        if isinstance(self.max_requests, bool) or self.max_requests < 1:
            raise ValueError("max_requests must be at least 1")

        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        if (
            isinstance(self.max_tracked_keys, bool)
            or self.max_tracked_keys < 1
        ):
            raise ValueError("max_tracked_keys must be at least 1")


@dataclass(slots=True)
class RateLimitBucket:
    """State for one rate-limit key."""

    window_started_at: float
    request_count: int = 0


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Result of a rate-limit evaluation."""

    allowed: bool
    remaining: int
    retry_after_seconds: float
    limit: int


class ConfigurationApiRateLimiter:
    """Process-local fixed-window rate limiter."""

    def __init__(
        self,
        policy: RateLimitPolicy | None = None,
    ) -> None:
        self.policy = policy or RateLimitPolicy()
        self._buckets: dict[str, RateLimitBucket] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> RateLimitResult:
        """Check and consume one request allowance."""

        if not isinstance(key, str) or not key.strip():
            raise ValueError("Rate-limit key must be non-empty")

        now = time.monotonic()
        policy = self.policy

        async with self._lock:
            bucket = self._buckets.get(key)

            if bucket is None:
                self._prune_expired(now)

                if len(self._buckets) >= policy.max_tracked_keys:
                    return RateLimitResult(
                        allowed=False,
                        remaining=0,
                        retry_after_seconds=policy.window_seconds,
                        limit=policy.max_requests,
                    )

                bucket = RateLimitBucket(
                    window_started_at=now,
                    request_count=0,
                )
                self._buckets[key] = bucket

            elapsed = now - bucket.window_started_at

            if elapsed >= policy.window_seconds:
                bucket.window_started_at = now
                bucket.request_count = 0

            if bucket.request_count >= policy.max_requests:
                retry_after = max(
                    0.0,
                    policy.window_seconds
                    - (now - bucket.window_started_at),
                )

                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    retry_after_seconds=retry_after,
                    limit=policy.max_requests,
                )

            bucket.request_count += 1

            return RateLimitResult(
                allowed=True,
                remaining=(
                    policy.max_requests - bucket.request_count
                ),
                retry_after_seconds=0.0,
                limit=policy.max_requests,
            )

    def _prune_expired(self, now: float) -> None:
        """Remove expired buckets to bound memory usage."""

        expired_keys = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.window_started_at >= self.policy.window_seconds
        ]

        for key in expired_keys:
            self._buckets.pop(key, None)

    async def reset(self, key: str | None = None) -> None:
        """Reset one rate-limit key or all tracked keys."""

        async with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)


@dataclass
class ConfigurationApiSecurity:
    """Security checks shared by configuration API endpoints."""

    rate_limiter: ConfigurationApiRateLimiter = field(
        default_factory=ConfigurationApiRateLimiter
    )

    async def validate_request(
        self,
        request: Request,
        principal: ConfigurationPrincipal,
    ) -> RateLimitResult:
        """Validate the principal and enforce request rate limits."""

        if not isinstance(principal, ConfigurationPrincipal):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authenticated principal",
            )

        if not principal.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authenticated principal is inactive",
            )

        if request.method not in {
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            raise HTTPException(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                detail="HTTP method is not supported",
            )

        key = (
            f"{principal.principal_id}:"
            f"{request.method}:"
            f"{request.url.path}"
        )

        result = await self.rate_limiter.check(key)

        if not result.allowed:
            logger.warning(
                "Configuration API rate limit exceeded: "
                "principal_id=%s path=%s",
                principal.principal_id,
                request.url.path,
            )

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many configuration API requests",
                headers={
                    "Retry-After": str(
                        max(1, int(result.retry_after_seconds))
                    ),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        return result
