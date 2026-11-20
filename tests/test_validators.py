import asyncio
import io

import pytest
from fastapi import UploadFile

from backend.config import settings
from backend.utils.validators import (
    AppError,
    detect_image_type,
    parse_question,
    read_and_validate_image,
)


def upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="x")


def validate(data: bytes):
    return asyncio.run(read_and_validate_image(upload(data)))


@pytest.mark.parametrize(
    "head, expected",
    [
        (b"\xff\xd8\xff" + b"0" * 20, "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n" + b"0" * 20, "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 20, "image/webp"),
        (b"\x00\x00\x00\x18ftypheic" + b"0" * 20, "image/heic"),
        (b"GIF89a" + b"0" * 20, None),
        (b"", None),
    ],
)
def test_detect_image_type(head, expected):
    assert detect_image_type(head) == expected


def test_valid_jpeg_accepted():
    assert validate(b"\xff\xd8\xff" + b"0" * 100).mime == "image/jpeg"


@pytest.mark.parametrize(
    "data, status, code",
    [
        (b"GIF89a" + b"0" * 100, 415, "UNSUPPORTED_FORMAT"),
        (b"", 400, "EMPTY_IMAGE"),
        (b"\xff\xd8\xff" + b"0" * (settings.max_file_size_bytes + 1), 413, "IMAGE_TOO_LARGE"),
    ],
)
def test_bad_images_rejected(data, status, code):
    with pytest.raises(AppError) as exc:
        validate(data)
    assert (exc.value.status_code, exc.value.error_code) == (status, code)


def test_missing_image_rejected():
    with pytest.raises(AppError) as exc:
        asyncio.run(read_and_validate_image(None))
    assert exc.value.error_code == "IMAGE_REQUIRED"


def test_question_is_trimmed():
    assert parse_question("  What is this?  ", None).question == "What is this?"


@pytest.mark.parametrize("question", ["hi", "", "x" * (settings.max_question_length + 1)])
def test_bad_question_rejected(question):
    with pytest.raises(AppError) as exc:
        parse_question(question, None)
    assert exc.value.error_code == "INVALID_QUESTION"


def test_bad_session_id_rejected():
    with pytest.raises(AppError) as exc:
        parse_question("What is this?", "abc")
    assert exc.value.error_code == "INVALID_SESSION"