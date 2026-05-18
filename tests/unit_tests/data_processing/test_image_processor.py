"""Unit tests for the image_processor module."""

import base64
import io
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from PIL import Image

from data_processing.image_processor import (
    ImageType,
    _convert_to_png,
    _downscale_image,
    download_image,
    get_mime_type,
    process_image,
)


def _make_png_bytes(width: int = 10, height: int = 10) -> bytes:
    """Return minimal PNG image bytes at the given dimensions."""
    img = Image.new("RGB", (width, height), color=(100, 149, 237))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg_bytes(width: int = 10, height: int = 10) -> bytes:
    """Return minimal JPEG image bytes at the given dimensions."""
    img = Image.new("RGB", (width, height), color=(255, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_gif_bytes(width: int = 10, height: int = 10) -> bytes:
    """Return minimal GIF image bytes at the given dimensions."""
    img = Image.new("P", (width, height))
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


class TestImageType:
    """Tests for the ImageType Pydantic model."""

    def test_auto_generates_id(self) -> None:
        """Test that id is auto-generated when not provided."""
        img = ImageType(url="http://example.com/a.jpg", mime_type="image/jpeg", base64="abc=")
        assert img.id
        assert isinstance(img.id, str)

    def test_custom_id_used(self) -> None:
        """Test that a provided id is stored as-is."""
        img = ImageType(
            id="my-id", url="http://example.com/a.jpg", mime_type="image/jpeg", base64="abc="
        )
        assert img.id == "my-id"

    def test_two_instances_have_different_auto_ids(self) -> None:
        """Test that auto-generated ids are unique across instances."""
        a = ImageType(url="http://x.com/a.jpg", mime_type="image/jpeg", base64="a=")
        b = ImageType(url="http://x.com/b.jpg", mime_type="image/jpeg", base64="b=")
        assert a.id != b.id

    def test_fields_stored_correctly(self) -> None:
        """Test that url, mime_type, and base64 are stored correctly."""
        img = ImageType(url="http://x.com/img.png", mime_type="image/png", base64="ZGF0YQ==")
        assert img.url == "http://x.com/img.png"
        assert img.mime_type == "image/png"
        assert img.base64 == "ZGF0YQ=="


class TestGetMimeType:
    """Tests for the get_mime_type function."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("http://x.com/img.jpg", "image/jpeg"),
            ("http://x.com/img.jpeg", "image/jpeg"),
            ("http://x.com/img.png", "image/png"),
            ("http://x.com/img.webp", "image/webp"),
            ("http://x.com/img.gif", "image/gif"),
            ("http://x.com/img.bmp", "image/bmp"),
            ("http://x.com/img.tiff", "image/tiff"),
            ("http://x.com/img.tif", "image/tiff"),
        ],
    )
    def test_known_extensions(self, url: str, expected: str) -> None:
        """Test that all supported extensions resolve to the correct MIME type."""
        assert get_mime_type(url) == expected

    def test_case_insensitive(self) -> None:
        """Test that uppercase extensions are resolved correctly."""
        assert get_mime_type("http://x.com/img.JPG") == "image/jpeg"
        assert get_mime_type("http://x.com/img.PNG") == "image/png"

    def test_query_params_ignored(self) -> None:
        """Test that query parameters do not affect MIME type resolution."""
        assert get_mime_type("http://x.com/img.png?width=100&height=200") == "image/png"

    def test_fragment_ignored(self) -> None:
        """Test that URL fragments do not affect MIME type resolution."""
        assert get_mime_type("http://x.com/img.jpg#section") == "image/jpeg"

    def test_unsupported_extension_raises(self) -> None:
        """Test that an unsupported extension raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported image format"):
            get_mime_type("http://x.com/img.svg")

    def test_no_extension_raises(self) -> None:
        """Test that a URL with no file extension raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported image format"):
            get_mime_type("http://x.com/image")


class TestConvertToPng:
    """Tests for the _convert_to_png helper."""

    def test_png_roundtrip(self) -> None:
        """Test that PNG bytes survive conversion and remain valid PNG."""
        png_bytes = _make_png_bytes()
        result = _convert_to_png(png_bytes)
        with Image.open(io.BytesIO(result)) as img:
            assert img.format == "PNG"

    def test_gif_converted_to_png(self) -> None:
        """Test that GIF input is converted to PNG output."""
        gif_bytes = _make_gif_bytes()
        result = _convert_to_png(gif_bytes)
        with Image.open(io.BytesIO(result)) as img:
            assert img.format == "PNG"

    def test_rgba_image_preserved(self) -> None:
        """Test that an RGBA image is converted without losing the alpha channel."""
        buf = io.BytesIO()
        Image.new("RGBA", (8, 8), (0, 0, 0, 128)).save(buf, format="PNG")
        result = _convert_to_png(buf.getvalue())
        with Image.open(io.BytesIO(result)) as img:
            assert img.mode == "RGBA"

    def test_invalid_bytes_raises_value_error(self) -> None:
        """Test that garbage bytes raise ValueError."""
        with pytest.raises(ValueError, match="Failed to convert image to PNG"):
            _convert_to_png(b"not-an-image")


class TestDownscaleImage:
    """Tests for the _downscale_image helper."""

    def test_small_image_returned_unchanged(self) -> None:
        """Test that an image already within the limit is returned as-is."""
        data = _make_png_bytes(10, 10)
        result = _downscale_image(data, max_size_bytes=10 * 1024 * 1024)
        assert result == data

    def test_oversized_image_is_reduced(self) -> None:
        """Test that an image exceeding the limit is reduced in byte size."""
        # Create a large PNG that will exceed the tiny threshold
        large_data = _make_png_bytes(500, 500)
        threshold = len(large_data) // 2
        result = _downscale_image(large_data, max_size_bytes=threshold)
        assert len(result) <= threshold or len(result) < len(large_data)

    def test_invalid_bytes_raises_value_error(self) -> None:
        """Test that invalid image bytes raise ValueError."""
        with pytest.raises(ValueError, match="Failed to downscale image"):
            _downscale_image(b"garbage", max_size_bytes=1)


class TestDownloadImage:
    """Tests for the download_image async function."""

    @pytest.mark.asyncio
    async def test_uses_provided_client(self) -> None:
        """Test that download_image uses the supplied client when provided."""
        mock_response = MagicMock()
        mock_response.content = b"image-bytes"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        result = await download_image("http://x.com/img.jpg", client=mock_client)

        assert result == b"image-bytes"
        mock_client.get.assert_awaited_once_with("http://x.com/img.jpg", timeout=10.0)
        mock_response.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_own_client_when_none(self) -> None:
        """Test that a temporary client is created when no client is passed."""
        mock_response = MagicMock()
        mock_response.content = b"data"
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("data_processing.image_processor.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = mock_client_instance
            result = await download_image("http://x.com/img.jpg")

        assert result == b"data"

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self) -> None:
        """Test that an HTTP error response is surfaced as HTTPStatusError."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            await download_image("http://x.com/img.jpg", client=mock_client)


class TestProcessImage:
    """Tests for the process_image orchestration function."""

    @pytest.fixture(name="png_bytes")
    def _png_bytes(self) -> bytes:
        """Return a small in-memory PNG."""
        return _make_png_bytes()

    @pytest.fixture(name="gif_bytes")
    def _gif_bytes(self) -> bytes:
        """Return a small in-memory GIF."""
        return _make_gif_bytes()

    @pytest.mark.asyncio
    async def test_returns_image_type(self, png_bytes: bytes) -> None:
        """Test that process_image returns an ImageType instance."""
        with patch(
            "data_processing.image_processor.download_image", new_callable=AsyncMock
        ) as mock_dl:
            mock_dl.return_value = png_bytes
            result = await process_image("http://x.com/img.png")

        assert isinstance(result, ImageType)

    @pytest.mark.asyncio
    async def test_url_and_mime_type_stored(self, png_bytes: bytes) -> None:
        """Test that url and mime_type are stored on the returned ImageType."""
        with patch(
            "data_processing.image_processor.download_image", new_callable=AsyncMock
        ) as mock_dl:
            mock_dl.return_value = png_bytes
            result = await process_image("http://x.com/photo.png")

        assert result.url == "http://x.com/photo.png"
        assert result.mime_type == "image/png"

    @pytest.mark.asyncio
    async def test_custom_id_forwarded(self, png_bytes: bytes) -> None:
        """Test that a custom img_id is used as the ImageType id."""
        with patch(
            "data_processing.image_processor.download_image", new_callable=AsyncMock
        ) as mock_dl:
            mock_dl.return_value = png_bytes
            result = await process_image("http://x.com/photo.png", img_id="custom-123")

        assert result.id == "custom-123"

    @pytest.mark.asyncio
    async def test_base64_is_valid(self, png_bytes: bytes) -> None:
        """Test that the base64 field decodes back to valid image bytes."""
        with patch(
            "data_processing.image_processor.download_image", new_callable=AsyncMock
        ) as mock_dl:
            mock_dl.return_value = png_bytes
            result = await process_image("http://x.com/photo.png")

        decoded = base64.b64decode(result.base64)
        with Image.open(io.BytesIO(decoded)) as img:
            assert img.format == "PNG"

    @pytest.mark.asyncio
    async def test_convertible_mime_type_converted_to_png(self, gif_bytes: bytes) -> None:
        """Test that GIF input is converted to PNG and mime_type updated."""
        with patch(
            "data_processing.image_processor.download_image", new_callable=AsyncMock
        ) as mock_dl:
            mock_dl.return_value = gif_bytes
            result = await process_image("http://x.com/anim.gif")

        assert result.mime_type == "image/png"
        decoded = base64.b64decode(result.base64)
        with Image.open(io.BytesIO(decoded)) as img:
            assert img.format == "PNG"

    @pytest.mark.asyncio
    async def test_non_convertible_mime_type_unchanged(self) -> None:
        """Test that JPEG input is not converted and mime_type stays image/jpeg."""
        jpeg = _make_jpeg_bytes()
        with patch(
            "data_processing.image_processor.download_image", new_callable=AsyncMock
        ) as mock_dl:
            mock_dl.return_value = jpeg
            result = await process_image("http://x.com/photo.jpg")

        assert result.mime_type == "image/jpeg"

    @pytest.mark.asyncio
    async def test_unsupported_url_raises_value_error(self) -> None:
        """Test that an unsupported image extension raises ValueError before downloading."""
        with pytest.raises(ValueError, match="Unsupported image format"):
            await process_image("http://x.com/doc.pdf")
