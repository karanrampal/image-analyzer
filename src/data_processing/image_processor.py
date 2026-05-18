"""Image processing utilities for downloading, converting, and preparing images."""

import asyncio
import base64
import io
import logging
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

_MIME_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}

_CONVERTIBLE_MIME_TYPES = frozenset({"image/gif", "image/bmp", "image/tiff"})


class ImageType(BaseModel):
    """Represents an image with its metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(
        default_factory=lambda: uuid4().hex,
        description="Unique identifier for the image",
    )
    url: str = Field(description="URL where the image is located")
    mime_type: str = Field(description="MIME type of the image")
    base64: str = Field(description="The image data in base64 encoding")


async def download_image(
    image_url: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Download an image from the given URL.

    Args:
        image_url: The URL of the image to download.
        client: Optional shared `httpx.AsyncClient`.  When `None` a
            temporary client is created (convenient but less efficient
            for batch processing).

    Returns:
        The content of the downloaded image.

    Raises:
        httpx.HTTPStatusError: If the server returns a 4xx/5xx response.
        httpx.RequestError: If a network-level error occurs.
    """
    if client is not None:
        response = await client.get(image_url, timeout=10.0)
        response.raise_for_status()
        return response.content

    async with httpx.AsyncClient() as _client:
        response = await _client.get(image_url, timeout=10.0)
        response.raise_for_status()
        return response.content


def get_mime_type(image_url: str) -> str:
    """Determine the MIME type of an image based on its URL.

    Extracts the file extension from the URL path, ignoring query
    parameters and fragments.

    Args:
        image_url: The URL of the image.

    Returns:
        The MIME type of the image.

    Raises:
        ValueError: If the image format is unsupported.
    """
    path = urlparse(image_url).path.lower()
    suffix = "." + path.rsplit(".", maxsplit=1)[-1] if "." in path else ""

    if mime_type := _MIME_TYPES.get(suffix):
        return mime_type

    raise ValueError(f"Unsupported image format for URL: {image_url}")


def _convert_to_png(image_data: bytes) -> bytes:
    """Convert image data to PNG format.

    Args:
        image_data: The original image data.

    Returns:
        The converted image data in PNG format.

    Raises:
        ValueError: If the conversion fails.
    """
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            mode = "RGBA" if img.mode in ("P", "RGBA", "LA", "PA") else "RGB"
            converted_img = img.convert(mode)

            buffer = io.BytesIO()
            converted_img.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
    except Exception as e:
        raise ValueError(f"Failed to convert image to PNG: {e}") from e


def _downscale_image(
    image_data: bytes,
    max_size_bytes: int = 7 * 1024 * 1024,
) -> bytes:
    """Downscale an image if it exceeds *max_size_bytes*.

    Uses an iterative approach: the pixel dimensions are reduced by an
    estimated scale factor derived from the byte-size ratio, then
    re-encoded.  If the result is still too large the process repeats
    (up to a fixed number of iterations) to account for the non-linear
    relationship between pixel count and compressed file size.

    Args:
        image_data: The original image data.
        max_size_bytes: The maximum allowed size in bytes.

    Returns:
        The (possibly downscaled) image data.

    Raises:
        ValueError: If the image cannot be processed within the
            iteration limit.
    """
    if len(image_data) <= max_size_bytes:
        return image_data

    max_iterations = 5
    current_data = image_data

    try:
        for iteration in range(max_iterations):
            with Image.open(io.BytesIO(current_data)) as img:
                img_format = img.format or "PNG"
                width, height = img.size
                scale = (max_size_bytes / len(current_data)) ** 0.5 * 0.9  # 10 % safety margin
                new_width = max(1, int(width * scale))
                new_height = max(1, int(height * scale))

                if new_width == width and new_height == height:
                    logger.warning(
                        "Cannot reduce dimensions further (%dx%d) - "
                        "returning best-effort result at %.2f MB",
                        width,
                        height,
                        len(current_data) / (1024 * 1024),
                    )
                    return current_data

                resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                buffer = io.BytesIO()
                resized.save(buffer, format=img_format, optimize=True)
                current_data = buffer.getvalue()

            logger.debug(
                "Downscale iteration %d: %dx%d -> %dx%d (%.2f MB)",
                iteration + 1,
                width,
                height,
                new_width,
                new_height,
                len(current_data) / (1024 * 1024),
            )

            if len(current_data) <= max_size_bytes:
                return current_data

        logger.warning(
            "Downscale did not converge after %d iterations - returning %.2f MB",
            max_iterations,
            len(current_data) / (1024 * 1024),
        )
        return current_data
    except Exception as e:
        raise ValueError(f"Failed to downscale image: {e}") from e


async def process_image(
    image_url: str,
    img_id: str | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> ImageType:
    """Download, convert, and downscale an image as needed.

    Args:
        image_url: The URL of the image to process.
        img_id: Optional ID for the image. A random hex ID is generated
            when not provided.
        client: Optional shared `httpx.AsyncClient` for efficient
            batch downloads.

    Returns:
        The processed image with its metadata.

    Raises:
        httpx.HTTPStatusError: If the image download gets a 4xx/5xx.
        httpx.RequestError: If a network-level error occurs.
        ValueError: If the image format is unsupported or conversion fails.
    """
    mime_type = get_mime_type(image_url)
    image_data = await download_image(image_url, client=client)
    logger.debug(
        "Processing image %s (mime=%s, size=%.2f MB)",
        image_url,
        mime_type,
        len(image_data) / (1024 * 1024),
    )

    if mime_type in _CONVERTIBLE_MIME_TYPES:
        image_data = await asyncio.to_thread(_convert_to_png, image_data)
        mime_type = "image/png"
        logger.debug("Converted to PNG (%.2f MB)", len(image_data) / (1024 * 1024))

    image_data = await asyncio.to_thread(_downscale_image, image_data)

    return ImageType(
        **({"id": img_id} if img_id is not None else {}),
        url=image_url,
        mime_type=mime_type,
        base64=base64.b64encode(image_data).decode(),
    )
