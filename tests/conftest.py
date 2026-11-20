import io
import os

# Must be set BEFORE backend is imported. Environment variables override .env,
# so tests always run with the mock model and known limits.
os.environ["MODEL_BACKEND"] = "mock"
os.environ["MAX_FILE_SIZE_MB"] = "5"
os.environ["SESSION_TTL_SECONDS"] = "600"

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app
from backend.services.model_service import model_service


@pytest.fixture
def make_image():
    def _make(fmt: str = "JPEG", size=(300, 200), color="orange") -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, fmt)
        return buf.getvalue()

    return _make


@pytest.fixture
def jpeg(make_image) -> bytes:
    return make_image("JPEG")


@pytest.fixture
def client():
    model_service.load()  # mock load is instant, so no startup race
    with TestClient(app) as c:
        yield c