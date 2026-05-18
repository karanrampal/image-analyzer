"""Unit tests for core.pipeline."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest

from core.pipeline import AsyncPipeline, PipelineStats, _MutableStats
from core.rate_limiter import RateLimiter


async def _identity_worker(item: int) -> int:
    """Worker that returns its input unchanged (always succeeds)."""
    return item


async def _none_worker(_item: int) -> int | None:
    """Worker that always returns None (every item is counted as failed)."""
    return None


async def _int_source(*items: int) -> AsyncIterator[int]:
    """Async generator yielding the supplied integers one at a time."""
    for item in items:
        yield item


def build_collect_sink(collected: list[int]) -> Callable[[list[int]], Awaitable[None]]:
    """Return an async sink that appends each batch's items to *collected*."""

    async def _sink(batch: list[int]) -> None:
        collected.extend(batch)

    return _sink


def build_pipeline(
    worker: Callable[[int], Awaitable[int | None]] = _identity_worker,
    num_workers: int = 2,
    flush_size: int = 10,
    rate_limiter: RateLimiter | None = None,
) -> AsyncPipeline[int, int]:
    """Convenience factory with sensible test defaults."""
    return AsyncPipeline(
        worker=worker,
        num_workers=num_workers,
        flush_size=flush_size,
        rate_limiter=rate_limiter,
        log_every=0,
    )


class TestPipelineStats:
    """Tests for the immutable PipelineStats result object."""

    def test_total_is_ok_plus_failed(self) -> None:
        """total must be the sum of ok and failed."""
        stats = PipelineStats(ok=7, failed=3, elapsed=1.0)
        assert stats.total == 10

    def test_throughput(self) -> None:
        """throughput must equal total / elapsed."""
        stats = PipelineStats(ok=10, failed=0, elapsed=2.0)
        assert stats.throughput == pytest.approx(5.0)

    def test_throughput_zero_elapsed(self) -> None:
        """Guard against division by zero when elapsed rounds to 0."""
        stats = PipelineStats(ok=1, failed=0, elapsed=0.0)
        assert stats.throughput == 0.0

    def test_str_contains_key_fields(self) -> None:
        """__str__ must include ok, failed, and total."""
        stats = PipelineStats(ok=3, failed=1, elapsed=2.0)
        s = str(stats)
        assert "ok=3" in s
        assert "failed=1" in s
        assert "total=4" in s

    def test_is_immutable(self) -> None:
        """Frozen dataclass must reject attribute assignment."""
        stats = PipelineStats(ok=1, failed=0, elapsed=1.0)
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            stats.ok = 99  # type: ignore[misc]


class TestMutableStats:
    """Tests for the internal mutable progress counter."""

    def test_initial_state(self) -> None:
        """All counters must start at zero."""
        s = _MutableStats(log_every=0)
        assert s.ok == 0
        assert s.failed == 0
        assert s.total == 0

    def test_record_success(self) -> None:
        """Recording a success increments ok only."""
        s = _MutableStats(log_every=0)
        s.record(success=True)
        assert s.ok == 1
        assert s.failed == 0

    def test_record_failure(self) -> None:
        """Recording a failure increments failed only."""
        s = _MutableStats(log_every=0)
        s.record(success=False)
        assert s.ok == 0
        assert s.failed == 1

    def test_total_aggregates(self) -> None:
        """total must equal the sum of all recorded outcomes."""
        s = _MutableStats(log_every=0)
        for _ in range(3):
            s.record(success=True)
        for _ in range(2):
            s.record(success=False)
        assert s.total == 5

    def test_snapshot_is_frozen(self) -> None:
        """A snapshot must be immutable and not reflect later mutations."""
        s = _MutableStats(log_every=0)
        s.record(success=True)
        snap = s.snapshot()
        assert isinstance(snap, PipelineStats)
        assert snap.ok == 1
        # Mutating _MutableStats after snapshot does not affect the snapshot.
        s.record(success=False)
        assert snap.failed == 0

    def test_log_every_zero_never_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """log_every=0 must never emit a progress log line."""
        s = _MutableStats(log_every=0)
        for _ in range(200):
            s.record(success=True)
        assert "Pipeline progress" not in caplog.text

    def test_log_every_triggers_at_interval(self, caplog: pytest.LogCaptureFixture) -> None:
        """A log line must appear every log_every processed items."""
        s = _MutableStats(log_every=5)
        with caplog.at_level(logging.INFO, logger="core.pipeline"):
            for _ in range(10):
                s.record(success=True)
        # Should have logged at total=5 and total=10.
        assert caplog.text.count("Pipeline progress") == 2


class TestAsyncPipelineConstruction:
    """Tests for invalid constructor arguments."""

    def test_zero_workers_raises(self) -> None:
        """num_workers=0 must raise ValueError."""
        with pytest.raises(ValueError, match="num_workers"):
            AsyncPipeline(worker=_identity_worker, num_workers=0, flush_size=10)

    def test_zero_flush_size_raises(self) -> None:
        """flush_size=0 must raise ValueError."""
        with pytest.raises(ValueError, match="flush_size"):
            AsyncPipeline(worker=_identity_worker, num_workers=1, flush_size=0)


class TestAsyncPipelineRun:
    """End-to-end tests for AsyncPipeline.run() with in-memory callables."""

    @pytest.mark.asyncio
    async def test_empty_source_returns_zero_stats(self) -> None:
        """An empty source must yield zero ok, zero failed, and an empty sink."""
        pipeline = build_pipeline()
        collected: list[int] = []
        stats = await pipeline.run(source=_int_source(), sink=build_collect_sink(collected))
        assert stats.ok == 0
        assert stats.failed == 0
        assert not collected

    @pytest.mark.asyncio
    async def test_all_items_processed(self) -> None:
        """Every item from the source must be processed and forwarded to the sink."""
        items = list(range(20))
        pipeline = build_pipeline(flush_size=5)
        collected: list[int] = []
        stats = await pipeline.run(source=_int_source(*items), sink=build_collect_sink(collected))
        assert stats.ok == 20
        assert stats.failed == 0
        assert sorted(collected) == items

    @pytest.mark.asyncio
    async def test_none_worker_counts_as_failed(self) -> None:
        """A worker returning None must count every item as failed and write nothing."""
        pipeline = build_pipeline(worker=_none_worker)
        collected: list[int] = []
        stats = await pipeline.run(source=_int_source(1, 2, 3), sink=build_collect_sink(collected))
        assert stats.ok == 0
        assert stats.failed == 3
        assert not collected

    @pytest.mark.asyncio
    async def test_mixed_worker_counts_both(self) -> None:
        """A worker that sometimes returns None must split ok/failed correctly."""

        async def mixed(item: int) -> int | None:
            return item if item % 2 == 0 else None

        pipeline = build_pipeline(worker=mixed)
        collected: list[int] = []
        stats = await pipeline.run(
            source=_int_source(1, 2, 3, 4), sink=build_collect_sink(collected)
        )
        assert stats.ok == 2
        assert stats.failed == 2
        assert sorted(collected) == [2, 4]

    @pytest.mark.asyncio
    async def test_stats_total_equals_source_length(self) -> None:
        """stats.total must equal the number of items yielded by the source."""
        items = list(range(50))
        pipeline = build_pipeline()
        collected: list[int] = []
        stats = await pipeline.run(source=_int_source(*items), sink=build_collect_sink(collected))
        assert stats.total == len(items)

    @pytest.mark.asyncio
    async def test_elapsed_is_positive(self) -> None:
        """stats.elapsed must be greater than zero after any run."""
        pipeline = build_pipeline()
        collected: list[int] = []
        stats = await pipeline.run(source=_int_source(1, 2, 3), sink=build_collect_sink(collected))
        assert stats.elapsed > 0

    @pytest.mark.asyncio
    async def test_total_hint_does_not_affect_results(self) -> None:
        """Passing total= is purely cosmetic; results must be identical."""
        pipeline = build_pipeline()
        collected: list[int] = []
        stats = await pipeline.run(
            source=_int_source(1, 2, 3),
            sink=build_collect_sink(collected),
            total=3,
        )
        assert stats.ok == 3


class TestAsyncPipelineSinkBatching:
    """Tests that the sink receives correctly-sized batches."""

    @pytest.mark.asyncio
    async def test_flush_size_respected(self) -> None:
        """Sink must not be called with a batch larger than flush_size."""
        flush_size = 5
        batch_sizes: list[int] = []

        async def recording_sink(batch: list[int]) -> None:
            batch_sizes.append(len(batch))

        pipeline = build_pipeline(flush_size=flush_size)
        await pipeline.run(source=_int_source(*range(13)), sink=recording_sink)

        assert all(s <= flush_size for s in batch_sizes)

    @pytest.mark.asyncio
    async def test_all_items_eventually_flushed(self) -> None:
        """Even the last partial batch (below flush_size) must reach the sink."""
        flush_size = 10
        collected: list[int] = []
        pipeline = build_pipeline(flush_size=flush_size)
        await pipeline.run(
            source=_int_source(*range(13)),  # 13 = one full batch + 3 remainder
            sink=build_collect_sink(collected),
        )
        assert sorted(collected) == list(range(13))

    @pytest.mark.asyncio
    async def test_sink_receives_separate_list_objects(self) -> None:
        """Each batch passed to the sink must be a distinct list (no shared reference)."""
        batches: list[list[int]] = []

        async def capturing_sink(batch: list[int]) -> None:
            batches.append(batch)

        pipeline = build_pipeline(flush_size=3)
        await pipeline.run(source=_int_source(*range(6)), sink=capturing_sink)

        assert len(batches) >= 2
        for i, a in enumerate(batches):
            for j, b in enumerate(batches):
                if i != j:
                    assert a is not b


class TestAsyncPipelineErrors:
    """Tests that exceptions in workers and sinks propagate correctly."""

    @pytest.mark.asyncio
    async def test_worker_exception_propagates(self) -> None:
        """An unhandled exception in a worker must bubble out of run()."""

        async def exploding_worker(item: int) -> int:
            raise RuntimeError("worker boom")

        pipeline = build_pipeline(worker=exploding_worker)
        collected: list[int] = []
        with pytest.raises(ExceptionGroup) as exc_info:
            await pipeline.run(source=_int_source(1), sink=build_collect_sink(collected))

        # Worker exceptions pass through two nested TaskGroups:
        #   inner (_run_workers) → ExceptionGroup([RuntimeError])
        #   outer (run)          → ExceptionGroup([ExceptionGroup([RuntimeError])])
        # Unwrap one level to find the RuntimeError.
        def _contains_runtime_error(eg: ExceptionGroup) -> bool:
            return any(
                isinstance(e, RuntimeError)
                or (isinstance(e, ExceptionGroup) and _contains_runtime_error(e))
                for e in eg.exceptions
            )

        assert _contains_runtime_error(exc_info.value)

    @pytest.mark.asyncio
    async def test_sink_exception_propagates(self) -> None:
        """An unhandled exception in the sink must bubble out of run()."""

        async def exploding_sink(batch: list[int]) -> None:
            raise RuntimeError("sink boom")

        pipeline = build_pipeline()
        with pytest.raises(ExceptionGroup) as exc_info:
            await pipeline.run(source=_int_source(1, 2, 3), sink=exploding_sink)
        assert any(isinstance(e, RuntimeError) for e in exc_info.value.exceptions)

    @pytest.mark.asyncio
    async def test_source_exception_propagates(self) -> None:
        """An exception raised by the source async generator must bubble out."""

        async def exploding_source() -> AsyncIterator[int]:
            yield 1
            raise RuntimeError("source boom")

        pipeline = build_pipeline()
        collected: list[int] = []
        with pytest.raises(ExceptionGroup) as exc_info:
            await pipeline.run(source=exploding_source(), sink=build_collect_sink(collected))
        assert any(isinstance(e, RuntimeError) for e in exc_info.value.exceptions)

    @pytest.mark.asyncio
    async def test_pipeline_completes_after_worker_returns_none(self) -> None:
        """None return is not an exception; the pipeline must complete normally."""
        pipeline = build_pipeline(worker=_none_worker)
        collected: list[int] = []
        await pipeline.run(source=_int_source(1, 2, 3), sink=build_collect_sink(collected))


class TestAsyncPipelineConcurrency:
    """Tests that verify concurrent execution behaviour."""

    @pytest.mark.asyncio
    async def test_multiple_workers_all_items_processed(self) -> None:
        """With multiple workers every item must still reach the sink."""
        pipeline = build_pipeline(num_workers=4)
        collected: list[int] = []
        stats = await pipeline.run(
            source=_int_source(*range(40)), sink=build_collect_sink(collected)
        )
        assert stats.ok == 40
        assert sorted(collected) == list(range(40))

    @pytest.mark.asyncio
    async def test_single_worker_preserves_order(self) -> None:
        """With one worker, output order must match input order."""
        pipeline = build_pipeline(num_workers=1, flush_size=100)
        collected: list[int] = []
        await pipeline.run(source=_int_source(*range(10)), sink=build_collect_sink(collected))
        assert collected == list(range(10))

    @pytest.mark.asyncio
    async def test_concurrent_workers_faster_than_sequential(self) -> None:
        """N concurrent workers should finish faster than N sequential workers would."""
        delay = 0.05  # 50 ms per item
        num_items = 4
        num_workers = num_items  # one worker per item → all run in parallel

        async def slow_worker(item: int) -> int:
            await asyncio.sleep(delay)
            return item

        pipeline = build_pipeline(worker=slow_worker, num_workers=num_workers)
        collected: list[int] = []
        t0 = time.monotonic()
        await pipeline.run(
            source=_int_source(*range(num_items)), sink=build_collect_sink(collected)
        )
        elapsed = time.monotonic() - t0

        # Sequential would take num_items * delay; parallel should be < 2 * delay.
        assert elapsed < num_items * delay
