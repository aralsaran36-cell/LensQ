from dataclasses import dataclass
from typing import Optional

from fastapi import UploadFile
from pydantic import ValidationError

from backend.config import settings
from backend.schemas.analyze import QuestionInput

HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"heif"}


class AppError(Exception):
    """Safe, expected error. The message never contains user input.
    main.py will turn this into an ErrorResponse JSON."""

    def __init__(self, status_code: int, error_code: str, message: str, retry: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.retry = retry


@dataclass
class ValidatedImage:
    data: bytes
    mime: str

    @property
    def size_kb(self) -> int:
        return round(len(self.data) / 1024)


def detect_image_type(head: bytes) -> Optional[str]:
    """Detect the real format from the file's first bytes (magic bytes).
    We do not trust the filename or the browser's content-type."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in HEIC_BRANDS:
        return "image/heic"
    return None


async def read_and_validate_image(upload: Optional[UploadFile]) -> ValidatedImage:
    if upload is None:
        raise AppError(400, "IMAGE_REQUIRED", "Please upload or capture an image.")

    # Read at most max+1 bytes, so a huge file can never fill the server RAM
    data = await upload.read(settings.max_file_size_bytes + 1)

    if not data:
        raise AppError(400, "EMPTY_IMAGE", "The image file is empty.")

    if len(data) > settings.max_file_size_bytes:
        raise AppError(
            413,
            "IMAGE_TOO_LARGE",
            f"Image is too large. Maximum size is {settings.max_file_size_mb} MB.",
        )

    mime = detect_image_type(data[:32])
    if mime is None or mime not in settings.allowed_image_types_list:
        raise AppError(
            415,
            "UNSUPPORTED_FORMAT",
            "Unsupported image format. Please use JPG, PNG, WebP or HEIC.",
        )

    return ValidatedImage(data=data, mime=mime)


def parse_question(question: Optional[str], session_id: Optional[str]) -> QuestionInput:
    """Runs the Pydantic checks and converts failures into a safe AppError."""
    try:
        return QuestionInput(question=question or "", session_id=session_id)
    except ValidationError as exc:
        # Only our own validator text is used. The user's input is never echoed back.
        first = exc.errors()[0]
        message = first.get("msg", "Invalid input.").removeprefix("Value error, ")
        field = first.get("loc", ("",))[0]
        code = "INVALID_SESSION" if field == "session_id" else "INVALID_QUESTION"
        raise AppError(400, code, message) from None