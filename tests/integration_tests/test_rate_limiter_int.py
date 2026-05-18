"""Integration tests for the RateLimiter class."""

import asyncio
import time

import pytest

from core.rate_limiter import RateLimiter


class TestRateLimiterZeroRate:
    """Tests for RateLimiter(0) — rate limiting disabled."""

    @pytest.mark.asyncio
    async def test_single_acquire_returns_immediately(self) -> None:
        """A single acquire() with rate=0 should not sleep at all."""
        limiter = RateLimiter(0)
        start = time.monotonic()
        await limiter.acquire()
        assert time.monotonic() - start < 0.05

    @pytest.mark.asyncio
    async def test_many_sequential_acquires_return_immediately(self) -> None:
        """Many sequential acquire() calls with rate=0 complete without measurable delay."""
        limiter = RateLimiter(0)
        start = time.monotonic()
        for _ in range(20):
            await limiter.acquire()
        assert time.monotonic() - start < 0.1

    @pytest.mark.asyncio
    async def test_concurrent_acquires_all_return_immediately(self) -> None:
        """Concurrent tasks calling acquire() with rate=0 all complete without delay."""
        limiter = RateLimiter(0)
        start = time.monotonic()
        async with asyncio.TaskGroup() as tg:
            for _ in range(10):
                tg.create_task(limiter.acquire())
        assert time.monotonic() - start < 0.1


class TestRateLimiterThrottling:
    """Tests verifying that a non-zero rate is actually enforced."""

    @pytest.mark.asyncio
    async def test_sequential_acquires_are_spaced_by_interval(self) -> None:
        """Sequential acquire() calls are separated by at least 1/rate seconds."""
        rate = 20.0  # one request every 50 ms
        limiter = RateLimiter(rate)
        min_interval = 1.0 / rate

        start = time.monotonic()
        for _ in range(4):
            await limiter.acquire()
        elapsed = time.monotonic() - start

        # First call is free; the 3 subsequent calls each wait ~50 ms
        expected_min = 3 * min_interval
        assert elapsed >= expected_min * 0.8  # 20 % tolerance for timer jitter

    @pytest.mark.asyncio
    async def test_concurrent_acquires_serialized_by_rate(self) -> None:
        """Concurrent tasks each acquire once; total time reflects serialized spacing."""
        rate = 20.0
        limiter = RateLimiter(rate)
        min_interval = 1.0 / rate

        start = time.monotonic()
        async with asyncio.TaskGroup() as tg:
            for _ in range(4):
                tg.create_task(limiter.acquire())
        elapsed = time.monotonic() - start

        # 4 tasks serialized: first is free, 3 subsequent wait ~50 ms each
        expected_min = 3 * min_interval
        assert elapsed >= expected_min * 0.8

    @pytest.mark.asyncio
    async def test_timestamps_increase_monotonically_by_interval(self) -> None:
        """Each completed acquire() is recorded after the previous one by at least 1/rate s."""
        rate = 20.0
        limiter = RateLimiter(rate)
        min_interval = 1.0 / rate

        timestamps: list[float] = []

        async def acquire_and_record() -> None:
            await limiter.acquire()
            timestamps.append(time.monotonic())

        async with asyncio.TaskGroup() as tg:
            for _ in range(4):
                tg.create_task(acquire_and_record())

        timestamps.sort()
        for i in range(1, len(timestamps)):
            gap = timestamps[i] - timestamps[i - 1]
            assert gap >= min_interval * 0.8, (
                f"Gap between acquisitions {i - 1}->{i} was {gap:.4f}s, "
                f"expected >= {min_interval * 0.8:.4f}s"
            )
