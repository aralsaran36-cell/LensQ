import asyncio
import io
import shutil
from dataclasses import dataclass

import pillow_heif
from PIL import Image, ImageOps

from backend.config import settings
from backend.utils.logger import get_logger, log_error, log_event
from backend.utils.validators import AppError, ValidatedImage

pillow_heif.register_heif_opener()

logger = get_logger(__name__)

# Decompression-bomb guard: a small file can hold a huge pixel count
MAX_PIXELS = 50_000_000
JPEG_QUALITY = 90
FFMPEG_TIMEOUT_SECONDS = 20


@dataclass
class PreparedImage:
    data: bytes  # always JPEG
    mime: str
    width: int
    height: int


def _processing_error() -> AppError:
    return AppError(
        422,
        "IMAGE_PROCESSING_FAILED",
        "Could not process this image. Please try another photo.",
    )


def _pillow_prepare(data: bytes) -> PreparedImage:
    """Decode, fix rotation, flatten transparency, resize, re-encode as JPEG.
    Re-encoding without EXIF also removes GPS/location data (privacy bonus)."""
    with Image.open(io.BytesIO(data)) as img:
        width, height = img.size  # lazy: pixels are not decoded yet
        if width * height > MAX_PIXELS:
            raise AppError(400, "IMAGE_DIMENSIONS_TOO_LARGE", "Image resolution is too high.")

        img = ImageOps.exif_transpose(img)

        if img.mode in ("RGBA", "LA") or "transparency" in img.info:
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[3])
            img = background
        else:
            img = img.convert("RGB")

        limit = settings.max_image_dimension
        if max(img.size) > limit:
            img.thumbnail((limit, limit), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=JPEG_QUALITY)  # no exif passed
        return PreparedImage(
            data=out.getvalue(), mime="image/jpeg", width=img.width, height=img.height
        )


async def _ffmpeg_prepare(data: bytes) -> PreparedImage:
    """Fallback. Image goes in through stdin and comes out through stdout,
    so nothing is written to disk."""
    if shutil.which("ffmpeg") is None:
        raise _processing_error()

    limit = settings.max_image_dimension
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-vf", f"scale='min({limit},iw)':'min({limit},ih)':force_original_aspect_ratio=decrease",
        "-frames:v", "1",
        "-q:v", "3",
        "-f", "mjpeg",
        "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,  # stderr is never logged or kept
    )
    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(input=data), timeout=FFMPEG_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise _processing_error() from None

    if proc.returncode != 0 or not stdout:
        raise _processing_error()

    try:
        with Image.open(io.BytesIO(stdout)) as check:
            return PreparedImage(
                data=stdout, mime="image/jpeg", width=check.width, height=check.height
            )
    except Exception:
        raise _processing_error() from None


async def prepare_image(image: ValidatedImage) -> PreparedImage:
    try:
        return await asyncio.to_thread(_pillow_prepare, image.data)
    except AppError:
        raise
    except Exception as exc:
        # Only the exception type is logged, never its message
        log_error(logger, "pillow_prepare_failed", exc, image_format=image.mime)

    result = await _ffmpeg_prepare(image.data)
    log_event(logger, "ffmpeg_fallback_used", status="ok", image_format=image.mime)
    return result