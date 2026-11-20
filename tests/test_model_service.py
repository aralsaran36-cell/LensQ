import asyncio

import httpx
import pytest

from backend.services import model_service as ms
from backend.utils.validators import AppError

IMAGE = b"\xff\xd8\xff" + b"0" * 50  # fake JPEG bytes, never decoded by LlamaCpp backend


def run(coro):
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, status_code=200, content="ok"):
        self.status_code = status_code
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class FakeClient:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    async def post(self, url, json=None):
        if self._error:
            raise self._error
        return self._response


def make_service(client):
    service = ms.LlamaCppModelService()
    service._loaded = True
    service._semaphore = asyncio.Semaphore(1)
    service._client = client
    return service


def test_backend_selection(monkeypatch):
    monkeypatch.setattr(ms.settings, "model_backend", "mock")
    assert isinstance(ms._build_model_service(), ms.MockModelService)
    monkeypatch.setattr(ms.settings, "model_backend", "llamacpp")
    assert isinstance(ms._build_model_service(), ms.LlamaCppModelService)
    monkeypatch.setattr(ms.settings, "model_backend", "transformers")
    assert isinstance(ms._build_model_service(), ms.ModelService)


def test_llamacpp_not_loaded_is_503():
    service = ms.LlamaCppModelService()
    with pytest.raises(AppError) as exc:
        run(service.answer(IMAGE, "What is this?"))
    assert exc.value.status_code == 503
    assert exc.value.error_code == "MODEL_NOT_READY"
    assert exc.value.retry is True


def test_llamacpp_server_down_is_503():
    service = make_service(FakeClient(error=httpx.ConnectError("down")))
    with pytest.raises(AppError) as exc:
        run(service.answer(IMAGE, "What is this?"))
    assert exc.value.status_code == 503
    assert exc.value.error_code == "MODEL_NOT_READY"
    assert exc.value.retry is True


def test_llamacpp_server_error_is_500():
    service = make_service(FakeClient(response=FakeResponse(status_code=500)))
    with pytest.raises(AppError) as exc:
        run(service.answer(IMAGE, "What is this?"))
    assert exc.value.status_code == 500
    assert exc.value.error_code == "INFERENCE_FAILED"
    assert exc.value.retry is True


def test_llamacpp_empty_answer_is_500():
    service = make_service(FakeClient(response=FakeResponse(content="   ")))
    with pytest.raises(AppError) as exc:
        run(service.answer(IMAGE, "What is this?"))
    assert exc.value.status_code == 500
    assert exc.value.error_code == "EMPTY_ANSWER"


def test_llamacpp_good_answer_strips_think_tags():
    service = make_service(
        FakeClient(response=FakeResponse(content="<think>hmm</think> The total is Rs 450."))
    )
    answer = run(service.answer(IMAGE, "What is the total?"))
    assert answer == "The total is Rs 450."