"""Rate limiter implementation for async use."""

import asyncio
import time


class RateLimiter:  # pylint: disable=too-few-public-methods
    """Simple token bucket rate limiter for async use."""

    def __init__(self, rate: float) -> None:
        """Initialise the rate limiter.

        Args:
            rate: Maximum number of requests per second. 0 disables limiting.
        """
        self._min_interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def acquire(self) -> None:
        """Wait until a request is allowed under the rate limit."""
        if self._min_interval == 0.0:
            return

        async with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._min_interval - (now - self._last_call))
            self._last_call = now + wait

        if wait > 0:
            await asyncio.sleep(wait)
