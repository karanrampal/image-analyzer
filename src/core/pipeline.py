"""Generic async producer-consumer pipeline with fan-out workers and a batched sink.

Overview
--------
The pipeline connects three stages through bounded in-memory queues::

    source  (AsyncIterable[ItemT])
        │  bounded row-queue   [maxsize = num_workers x 2]
        ▼
    N async workers  (optionally rate-limited)
        │  bounded write-queue  [maxsize = flush_size x 2]
        ▼
    batched sink  (called with up to flush_size results at a time)

Back-pressure is built-in: if the sink is slow the write-queue fills up, which
blocks workers from picking new items, which in turn fills the row-queue and
stalls the source.  No items are silently dropped because of queue pressure.

Typical usage
-------------
::

    from core.pipeline import AsyncPipeline, RateLimiter

    async def my_worker(item: MyInput) -> MyOutput | None:
        # Return None to signal that the item should be skipped / counted as failed.
        ...

    async def my_sink(batch: list[MyOutput]) -> None:
        # Write the batch somewhere (database, file, …).
        ...

    async def my_source() -> AsyncIterator[MyInput]:
        for row in rows:
            yield row

    pipeline = AsyncPipeline(
        worker=my_worker,
        num_workers=8,
        flush_size=100,
        rate_limiter=RateLimiter(rate=5.0),
    )
    stats = await pipeline.run(source=my_source(), sink=my_sink)
    print(stats)
"""

import asyncio
import dataclasses
import logging
import time
from collections.abc import AsyncIterable, Awaitable, Callable
from typing import cast

from core.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class _Sentinel:  # pylint: disable=too-few-public-methods
    """Unique sentinel type used to signal end-of-stream on internal queues."""


_SENTINEL = _Sentinel()


@dataclasses.dataclass(frozen=True)
class PipelineStats:
    """Immutable summary of a completed pipeline run.

    Attributes:
        ok:      Items the worker returned a non-None result for (sent to sink).
        failed:  Items the worker returned ``None`` for (skipped / errored).
        elapsed: Wall-clock seconds from ``run()`` call to completion.
    """

    ok: int
    failed: int
    elapsed: float

    @property
    def total(self) -> int:
        """Total items consumed from the source (ok + failed)."""
        return self.ok + self.failed

    @property
    def throughput(self) -> float:
        """Processed items per second over the full run."""
        return self.total / self.elapsed if self.elapsed > 0 else 0.0

    def __str__(self) -> str:
        return (
            f"PipelineStats(ok={self.ok}, failed={self.failed}, "
            f"total={self.total}, elapsed={self.elapsed:.2f}s, "
            f"throughput={self.throughput:.1f} items/s)"
        )


class _MutableStats:
    """Mutable progress counters shared across worker coroutines.

    Safe for concurrent access within a single asyncio event loop because asyncio uses cooperative
    multitasking — counter increments are atomic between ``await`` points.
    """

    __slots__ = ("ok", "failed", "_log_every", "_start", "_total_rows")

    def __init__(self, log_every: int, total_rows: int | None = None) -> None:
        self.ok = 0
        self.failed = 0
        self._log_every = log_every
        self._start = time.monotonic()
        self._total_rows = total_rows

    @property
    def total(self) -> int:
        """Total items processed (ok + failed)."""
        return self.ok + self.failed

    def record(self, *, success: bool) -> None:
        """Increment the appropriate counter and optionally log progress."""
        if success:
            self.ok += 1
        else:
            self.failed += 1
        if self._log_every > 0 and self.total % self._log_every == 0:
            self._log()

    def _log(self) -> None:
        elapsed = time.monotonic() - self._start
        rate = self.total / elapsed if elapsed > 0 else 0.0
        if self._total_rows is not None:
            logger.info(
                "Pipeline progress: %d ok, %d failed (%d/%d processed, %.1f items/s).",
                self.ok,
                self.failed,
                self.total,
                self._total_rows,
                rate,
            )
        else:
            logger.info(
                "Pipeline progress: %d ok, %d failed (%d total, %.1f items/s).",
                self.ok,
                self.failed,
                self.total,
                rate,
            )

    def snapshot(self) -> PipelineStats:
        """Return an immutable :class:`PipelineStats` from the current state."""
        return PipelineStats(
            ok=self.ok,
            failed=self.failed,
            elapsed=time.monotonic() - self._start,
        )


class AsyncPipeline[ItemT, ResultT]:  # pylint: disable=too-few-public-methods
    """Fan-out producer-consumer pipeline with a batched sink.

    Args:
        worker: Async callable `(item: ItemT) -> ResultT | None`. Return ``None`` to skip an item
            (it is counted as *failed* and never forwarded to the sink).
        num_workers: Number of concurrent worker coroutines.
        flush_size: Maximum number of results to buffer before calling the sink. The sink may
            receive smaller batches when the source is exhausted.
        rate_limiter: Optional `RateLimiter` applied *before* each worker call. `None` (default)
            means no limiting.
        log_every: Emit a progress log line every *n* processed items. `0` disables periodic
            logging.
    """

    def __init__(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self,
        worker: Callable[[ItemT], Awaitable[ResultT | None]],
        num_workers: int,
        flush_size: int,
        rate_limiter: RateLimiter | None = None,
        log_every: int = 100,
    ) -> None:
        if num_workers < 1:
            raise ValueError("num_workers must be at least 1.")
        if flush_size < 1:
            raise ValueError("flush_size must be at least 1.")

        self._worker = worker
        self._num_workers = num_workers
        self._flush_size = flush_size
        self._rate_limiter = rate_limiter or RateLimiter(0.0)
        self._log_every = log_every

    async def run(
        self,
        source: AsyncIterable[ItemT],
        sink: Callable[[list[ResultT]], Awaitable[None]],
        total: int | None = None,
    ) -> PipelineStats:
        """Run the pipeline until *source* is exhausted.

        Internally this creates three asyncio tasks that run concurrently inside an
        `asyncio.TaskGroup`:

        * `_produce`      — iterates *source* and fills the row-queue.
        * `_run_workers`  — spawns all workers; signals the writer when done.
        * `_drain`        — collects results and calls *sink* in batches.

        `asyncio.TaskGroup` guarantees that if *any* task raises an unhandled exception all
        remaining tasks are cancelled before the exception propagates to the caller.

        Args:
            source: Async iterable that yields one input item at a time. Use `asyncio.to_thread`
                inside an async-generator wrapper to adapt a blocking/synchronous data source.
            sink: Async callable that persists a batch of results. Called with a non-empty
                `list[ResultT]`.
            total: Optional total number of items in *source*.

        Returns:
            `PipelineStats` with final ok/failed counts and elapsed time.
        """
        row_queue: asyncio.Queue[ItemT | _Sentinel] = asyncio.Queue(
            maxsize=self._num_workers * 2,
        )
        write_queue: asyncio.Queue[ResultT | _Sentinel] = asyncio.Queue(
            maxsize=self._flush_size * 2,
        )
        stats = _MutableStats(self._log_every, total_rows=total)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._produce(source, row_queue))
            tg.create_task(self._run_workers(row_queue, write_queue, stats))
            tg.create_task(self._drain(write_queue, sink))

        return stats.snapshot()

    async def _produce(
        self,
        source: AsyncIterable[ItemT],
        row_queue: asyncio.Queue[ItemT | _Sentinel],
    ) -> None:
        """Iterate *source* and enqueue items.

        The `finally` block sends exactly one `_SENTINEL` per worker so every worker stops cleanly
        regardless of whether the source raises or is exhausted normally.
        """
        try:
            async for item in source:
                await row_queue.put(item)
        finally:
            for _ in range(self._num_workers):
                await row_queue.put(_SENTINEL)

    async def _work(
        self,
        row_queue: asyncio.Queue[ItemT | _Sentinel],
        write_queue: asyncio.Queue[ResultT | _Sentinel],
        stats: _MutableStats,
    ) -> None:
        """Single worker loop: dequeue → rate-limit → call worker → enqueue result."""
        while True:
            item = await row_queue.get()
            try:
                if item is _SENTINEL:
                    return

                await self._rate_limiter.acquire()
                result = await self._worker(cast(ItemT, item))

                if result is not None:
                    await write_queue.put(result)
                stats.record(success=result is not None)
            finally:
                row_queue.task_done()

    async def _run_workers(
        self,
        row_queue: asyncio.Queue[ItemT | _Sentinel],
        write_queue: asyncio.Queue[ResultT | _Sentinel],
        stats: _MutableStats,
    ) -> None:
        """Spawn all workers concurrently; signal the drainer when all finish.

        Wrapping workers in a nested `asyncio.TaskGroup` means that if any worker raises an
        unhandled exception its siblings are cancelled before the sentinel is forwarded to the
        write-queue. Because this task and `_drain` are siblings in the *outer* TaskGroup, a
        drainer failure also cancels this task (and all workers blocked on a full write-queue),
        preventing deadlocks.
        """
        async with asyncio.TaskGroup() as tg:
            for _ in range(self._num_workers):
                tg.create_task(self._work(row_queue, write_queue, stats))
        await write_queue.put(_SENTINEL)

    async def _drain(
        self,
        write_queue: asyncio.Queue[ResultT | _Sentinel],
        sink: Callable[[list[ResultT]], Awaitable[None]],
    ) -> None:
        """Collect results and flush them to *sink* in batches of flush_size."""
        buffer: list[ResultT] = []
        total_written = 0

        while True:
            item = await write_queue.get()
            if item is _SENTINEL:
                write_queue.task_done()
                break
            buffer.append(cast(ResultT, item))
            write_queue.task_done()

            if len(buffer) >= self._flush_size:
                await sink(buffer)
                total_written += len(buffer)
                logger.debug("Flushed %d items (%d total written).", len(buffer), total_written)
                buffer = []  # Dereference; don't mutate the list sink may still hold.

        if buffer:
            await sink(buffer)
            total_written += len(buffer)

        logger.info("Sink done: %d items written.", total_written)
