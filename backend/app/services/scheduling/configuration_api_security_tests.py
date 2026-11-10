"""Tests for scheduling configuration API security utilities."""

from __future__ import annotations

import pytest

from app.services.scheduling.configuration_api_security import (
    ConfigurationApiRateLimiter,
    RateLimitPolicy,
)


class TestRateLimitPolicy:
    def test_default_policy(self) -> None:
        policy = RateLimitPolicy()

        assert policy.max_requests == 60
        assert policy.window_seconds == 60.0
        assert policy.max_tracked_keys == 10_000

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_requests": 0},
            {"max_requests": -1},
            {"window_seconds": 0},
            {"window_seconds": -1},
            {"max_tracked_keys": 0},
            {"max_tracked_keys": -1},
        ],
    )
    def test_invalid_policy_is_rejected(
        self,
        kwargs: dict,
    ) -> None:
        with pytest.raises(ValueError):
            RateLimitPolicy(**kwargs)


class TestConfigurationApiRateLimiter:
    @pytest.mark.asyncio
    async def test_first_request_is_allowed(self) -> None:
        limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy(max_requests=3)
        )

        result = await limiter.check("principal-1")

        assert result.allowed is True
        assert result.remaining == 2
        assert result.limit == 3
        assert result.retry_after_seconds == 0

    @pytest.mark.asyncio
    async def test_requests_within_limit_are_allowed(self) -> None:
        limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy(max_requests=3)
        )

        results = [
            await limiter.check("principal-1")
            for _ in range(3)
        ]

        assert all(result.allowed for result in results)
        assert [result.remaining for result in results] == [
            2,
            1,
            0,
        ]

    @pytest.mark.asyncio
    async def test_request_exceeding_limit_is_rejected(self) -> None:
        limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy(max_requests=2)
        )

        await limiter.check("principal-1")
        await limiter.check("principal-1")

        result = await limiter.check("principal-1")

        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after_seconds > 0
        assert result.limit == 2

    @pytest.mark.asyncio
    async def test_different_keys_have_independent_limits(self) -> None:
        limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy(max_requests=1)
        )

        first = await limiter.check("principal-1")
        second = await limiter.check("principal-2")

        assert first.allowed is True
        assert second.allowed is True

    @pytest.mark.asyncio
    async def test_empty_key_is_rejected(self) -> None:
        limiter = ConfigurationApiRateLimiter()

        with pytest.raises(ValueError):
            await limiter.check("")

    @pytest.mark.asyncio
    async def test_whitespace_key_is_rejected(self) -> None:
        limiter = ConfigurationApiRateLimiter()

        with pytest.raises(ValueError):
            await limiter.check("   ")

    @pytest.mark.asyncio
    async def test_reset_specific_key(self) -> None:
        limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy(max_requests=1)
        )

        await limiter.check("principal-1")
        await limiter.reset("principal-1")

        result = await limiter.check("principal-1")

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_reset_all_keys(self) -> None:
        limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy(max_requests=1)
        )

        await limiter.check("principal-1")
        await limiter.check("principal-2")

        await limiter.reset()

        first = await limiter.check("principal-1")
        second = await limiter.check("principal-2")

        assert first.allowed is True
        assert second.allowed is True

    @pytest.mark.asyncio
    async def test_expired_window_allows_new_requests(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import app.services.scheduling.configuration_api_security as security

        current_time = 100.0

        monkeypatch.setattr(
            security.time,
            "monotonic",
            lambda: current_time,
        )

        limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy(
                max_requests=1,
                window_seconds=10,
            )
        )

        first = await limiter.check("principal-1")
        assert first.allowed is True

        current_time += 11

        second = await limiter.check("principal-1")
        assert second.allowed is True

    @pytest.mark.asyncio
    async def test_expired_buckets_are_pruned(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import app.services.scheduling.configuration_api_security as security

        current_time = 100.0

        monkeypatch.setattr(
            security.time,
            "monotonic",
            lambda: current_time,
        )

        limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy(
                max_requests=2,
                window_seconds=5,
                max_tracked_keys=2,
            )
        )

        await limiter.check("principal-1")
        await limiter.check("principal-2")

        assert len(limiter._buckets) == 2

        current_time += 6

        await limiter.check("principal-3")

        assert "principal-1" not in limiter._buckets
        assert "principal-2" not in limiter._buckets
        assert "principal-3" in limiter._buckets

    @pytest.mark.asyncio
    async def test_bucket_limit_rejects_new_keys(self) -> None:
        limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy(
                max_requests=5,
                max_tracked_keys=1,
            )
        )

        first = await limiter.check("principal-1")
        second = await limiter.check("principal-2")

        assert first.allowed is True
        assert second.allowed is False

    @pytest.mark.asyncio
    async def test_existing_key_works_when_bucket_limit_is_reached(
        self,
    ) -> None:
        limiter = ConfigurationApiRateLimiter(
            RateLimitPolicy(
                max_requests=2,
                max_tracked_keys=1,
            )
        )

        await limiter.check("principal-1")

        result = await limiter.check("principal-1")

        assert result.allowed is True
        assert result.remaining == 0
