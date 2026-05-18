"""Performance tests for the pipeline module."""

from pytest_benchmark.fixture import BenchmarkFixture

from core.pipeline import _MutableStats


class TestProgressTrackerPerformance:
    """Benchmarks for the _MutableStats counters in the worker hot-path."""

    def test_record_success(self, benchmark: BenchmarkFixture) -> None:
        """Cost of recording a successful annotation (the common case)."""
        # log_every=0 disables periodic logging so only the counter increment is timed
        tracker = _MutableStats(log_every=0)
        benchmark(tracker.record, success=True)

    def test_record_failure(self, benchmark: BenchmarkFixture) -> None:
        """Cost of recording a failed annotation."""
        tracker = _MutableStats(log_every=0)
        benchmark(tracker.record, success=False)
