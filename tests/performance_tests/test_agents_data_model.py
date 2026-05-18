"""Performance tests for the agents' data models."""

from pytest_benchmark.fixture import BenchmarkFixture

from agents.instructions.data_models import FashionImageAnnotation, ModelEnum


class TestAnnotationSerializationPerformance:  # pylint: disable=too-few-public-methods
    """Benchmarks for Pydantic serialisation of the annotation output model."""

    def test_model_dump(
        self, benchmark: BenchmarkFixture, annotation: FashionImageAnnotation
    ) -> None:
        """Cost of model_dump() — called once per annotated row in the writer hot-path."""
        result = benchmark(annotation.model_dump)
        assert result["model"] == ModelEnum.YES
