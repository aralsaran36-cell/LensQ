import asyncio
import base64
import io
import re
import time
from typing import Optional

import httpx
from PIL import Image

from backend.config import settings
from backend.utils.logger import get_logger, log_error, log_event
from backend.utils.validators import AppError

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "Answer questions about the provided image. "
    "Base every answer only on what can be seen. "
    "Reply in plain text only: no markdown, no asterisks, no headings. "
    "Be clear, direct and concise. If something is not visible or unreadable, say so."
)
THINK_TAG = re.compile(r"<think>.*?</think>", re.DOTALL)
MD_BULLET = re.compile(r"^[ \t]*[*\-][ \t]+", re.MULTILINE)
MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
MD_ITALIC = re.compile(r"(?<!\*)\*(?![\s*])([^*\n]+?)\*(?!\*)")
MD_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.MULTILINE)


def clean_answer(text: str) -> str:
    """Removes <think> tags and markdown symbols so the answer reads as plain text."""
    text = THINK_TAG.sub("", text)
    text = MD_BULLET.sub("• ", text)
    text = MD_BOLD.sub(r"\1", text)
    text = MD_ITALIC.sub(r"\1", text)
    text = MD_HEADING.sub("", text)
    text = text.replace("`", "")
    return text.strip()


def _not_ready() -> AppError:
    return AppError(
        503, "MODEL_NOT_READY", "The model is still loading. Please try again shortly.", retry=True
    )


class ModelService:
    def __init__(self) -> None:
        self.model = None
        self.processor = None
        self.device: str = "cpu"
        self._semaphore: Optional[asyncio.Semaphore] = None

    @property
    def is_loaded(self) -> bool:
        return self.model is not None and self.processor is not None

    def _resolve_device(self):
        import torch  # type: ignore  # lazy: only needed for the real model

        wanted = settings.model_device.lower()
        if wanted == "auto":
            # Same rule as the official model card: cuda if available, else cpu
            wanted = "cuda" if torch.cuda.is_available() else "cpu"
        if wanted == "cuda":
            return "cuda", torch.bfloat16
        if wanted == "mps":
            # Not covered by the model card. Experimental.
            return "mps", torch.bfloat16
        return "cpu", torch.float32

    def load(self) -> None:
        """Blocking. Called once at startup (main.py runs it in a thread)."""
        if self.is_loaded:
            return
        from transformers import AutoModelForMultimodalLM, AutoProcessor  # type: ignore  # lazy

        device, dtype = self._resolve_device()
        start = time.perf_counter()

        self.processor = AutoProcessor.from_pretrained(
            settings.model_id, trust_remote_code=True
        )
        self.model = AutoModelForMultimodalLM.from_pretrained(
            settings.model_id,
            dtype=dtype,
            device_map=device,
            trust_remote_code=True,
        ).eval()

        self.device = device
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_inference)
        log_event(
            logger,
            "model_loaded",
            status="ok",
            model_id=settings.model_id,
            device=device,
            latency_ms=round((time.perf_counter() - start) * 1000),
        )

    def unload(self) -> None:
        self.model = None
        self.processor = None

    def _generate_sync(self, image_bytes: bytes, question: str) -> str:
        import torch  # type: ignore  # lazy

        # Image is decoded from memory. Nothing is written to disk.
        with Image.open(io.BytesIO(image_bytes)) as img:
            image = img.convert("RGB")

        conversation = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": question},
                ],
            },
        ]
        inputs = self.processor.apply_chat_template(
            conversation,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=settings.max_new_tokens,
                generation_mode="text",
            )

        text = self.processor.decode(
            outputs.sequences[0, inputs["input_ids"].shape[1]:outputs.sequence_lengths[0]],
            skip_special_tokens=True,
        )
        return clean_answer(text)

    async def answer(self, image_bytes: bytes, question: str) -> str:
        if not self.is_loaded or self._semaphore is None:
            raise _not_ready()

        async with self._semaphore:  # limits parallel inference (RAM/GPU safety)
            try:
                text = await asyncio.to_thread(self._generate_sync, image_bytes, question)
            except Exception as exc:
                log_error(logger, "inference_failed", exc, device=self.device)
                raise AppError(
                    500, "INFERENCE_FAILED", "Could not analyze the image. Please try again.", retry=True
                ) from None

        if not text:
            raise AppError(500, "EMPTY_ANSWER", "The model returned no answer. Please try again.", retry=True)
        return text


class MockModelService:
    """Development only. Same interface as ModelService, but it does NOT look at
    the image. Used on machines where torch cannot run (e.g. Intel Mac)."""

    def __init__(self) -> None:
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        self._loaded = True
        log_event(logger, "model_loaded", status="ok", model_id="mock", device="none")

    def unload(self) -> None:
        self._loaded = False

    async def answer(self, image_bytes: bytes, question: str) -> str:
        if not self._loaded:
            raise _not_ready()
        await asyncio.sleep(0.3)  # simulate latency
        return "[MOCK ANSWER] The real model is disabled. This is a placeholder response."


class LlamaCppModelService:
    """Calls a local llama.cpp server (GGUF) over HTTP. The image is sent as a
    base64 data URI built in memory. Nothing is written to disk."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Blocking health check. Called once at startup in a thread."""
        base = settings.llamacpp_base_url.rstrip("/")
        try:
            resp = httpx.get(f"{base}/health", timeout=5.0)
            ok = resp.status_code == 200
        except Exception as exc:
            log_error(logger, "llamacpp_unreachable", exc)
            ok = False
        if not ok:
            # Stay not-loaded: /health shows "degraded", /analyze returns 503.
            return
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_inference)
        self._loaded = True
        log_event(logger, "model_loaded", status="ok", model_id="llamacpp", device="llamacpp")

    def unload(self) -> None:
        self._loaded = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.llamacpp_base_url.rstrip("/"),
                timeout=httpx.Timeout(settings.llamacpp_timeout_seconds, connect=5.0),
            )
        return self._client

    async def answer(self, image_bytes: bytes, question: str) -> str:
        if not self._loaded or self._semaphore is None:
            raise _not_ready()

        b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": question},
                    ],
                },
            ],
            "max_tokens": settings.max_new_tokens,
            "temperature": 0,
        }

        async with self._semaphore:
            try:
                client = await self._get_client()
                resp = await client.post("/v1/chat/completions", json=payload)
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"] or ""
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                log_error(logger, "llamacpp_unreachable", exc)
                raise _not_ready() from None
            except Exception as exc:
                log_error(logger, "inference_failed", exc, device="llamacpp")
                raise AppError(
                    500, "INFERENCE_FAILED", "Could not analyze the image. Please try again.", retry=True
                ) from None

        text = clean_answer(text)
        if not text:
            raise AppError(500, "EMPTY_ANSWER", "The model returned no answer. Please try again.", retry=True)
        return text


def _build_model_service():
    if settings.model_backend == "mock":
        return MockModelService()
    if settings.model_backend == "llamacpp":
        return LlamaCppModelService()
    return ModelService()


model_service = _build_model_service()