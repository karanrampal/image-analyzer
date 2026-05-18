"""Unit tests for core.rate_limiter."""

import asyncio
import time

import pytest

from core.rate_limiter import RateLimiter


class TestRateLimiter:
    """Tests for the standalone RateLimiter helper."""

    @pytest.mark.asyncio
    async def test_zero_rate_returns_immediately(self) -> None:
        """rate=0 must return immediately without sleeping."""
        rl = RateLimiter(rate=0.0)
        await asyncio.wait_for(rl.acquire(), timeout=0.1)

    @pytest.mark.asyncio
    async def test_high_rate_returns_quickly(self) -> None:
        """1000 rps → min_interval=1 ms; two back-to-back calls must finish fast."""
        rl = RateLimiter(rate=1000.0)
        await rl.acquire()
        await asyncio.wait_for(rl.acquire(), timeout=0.5)

    @pytest.mark.asyncio
    async def test_rate_is_enforced(self) -> None:
        """2 rps → ≥ 0.5 s between calls; two calls should take at least 0.4 s."""
        rl = RateLimiter(rate=2.0)
        await rl.acquire()
        t0 = time.monotonic()
        await rl.acquire()
        elapsed = time.monotonic() - t0
        # Allow generous lower bound to avoid flakiness on slow CI.
        assert elapsed >= 0.4
