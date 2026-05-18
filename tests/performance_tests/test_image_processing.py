"""Performance benchmarks for CPU-bound image-processing and annotation hot-path code."""

import io

import pytest
from PIL import Image
from pytest_benchmark.fixture import BenchmarkFixture

from data_processing.image_processor import _convert_to_png, _downscale_image

_7MB = 7 * 1024 * 1024


@pytest.fixture(scope="session", name="small_png_bytes")
def _small_png_bytes() -> bytes:
    """Return a ~30 KB solid-colour PNG (well below the 7 MB downscale limit)."""
    img = Image.new("RGB", (100, 100), color=(127, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="session", name="large_png_bytes")
def _large_png_bytes() -> bytes:
    """Return a >7 MB uncompressed PNG to force at least one downscale iteration.

    2000x2000 RGB with a repeating byte pattern saved at compress_level=0.
    Uncompressed pixel data ≈ 12 MB, so the on-disk size is well above 7 MB
    and at least one resize iteration is guaranteed.
    """
    size = 2000
    raw = (bytes(range(256)) * ((size * size * 3 // 256) + 1))[: size * size * 3]
    img = Image.frombytes("RGB", (size, size), raw)
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=0)
    return buf.getvalue()


@pytest.fixture(scope="session", name="gif_bytes")
def _gif_bytes() -> bytes:
    """Return a 500x500 palette-indexed GIF (requires conversion before downscale)."""
    img = Image.new("P", (500, 500))
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


@pytest.fixture(scope="session", name="bmp_bytes")
def _bmp_bytes() -> bytes:
    """Return a 500x500 uncompressed BMP (requires conversion before downscale)."""
    img = Image.new("RGB", (500, 500), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()


class TestDownscaleImagePerformance:
    """Benchmarks for _downscale_image across the no-op and resize paths."""

    def test_small_image_no_op(self, benchmark: BenchmarkFixture, small_png_bytes: bytes) -> None:
        """Fast-path baseline: a sub-limit image is returned immediately without any work."""
        result = benchmark(_downscale_image, small_png_bytes)
        # Sanity-check: data is unchanged
        assert result == small_png_bytes

    def test_large_image_resize(self, benchmark: BenchmarkFixture, large_png_bytes: bytes) -> None:
        """Cost of resizing a >7 MB image until it fits under the byte limit."""
        result = benchmark(_downscale_image, large_png_bytes)
        assert len(result) <= _7MB


class TestConvertToPngPerformance:
    """Benchmarks for _convert_to_png across the supported convertible formats."""

    def test_convert_gif(self, benchmark: BenchmarkFixture, gif_bytes: bytes) -> None:
        """Cost of palette GIF → RGBA PNG conversion."""
        result = benchmark(_convert_to_png, gif_bytes)
        assert result[:4] == b"\x89PNG"

    def test_convert_bmp(self, benchmark: BenchmarkFixture, bmp_bytes: bytes) -> None:
        """Cost of uncompressed BMP → RGB PNG conversion."""
        result = benchmark(_convert_to_png, bmp_bytes)
        assert result[:4] == b"\x89PNG"
