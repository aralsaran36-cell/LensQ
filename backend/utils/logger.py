import logging
import sys
import time
from contextlib import contextmanager

from backend.config import settings

# Only these fields are allowed in logs. Anything else is dropped silently,
# so image bytes, question text and answers can never leak by mistake.
ALLOWED_FIELDS = {
    "status",
    "status_code",
    "latency_ms",
    "error_code",
    "error_type",
    "session_id",
    "request_id",
    "image_size_kb",
    "image_format",
    "width",
    "height",
    "device",
    "model_id",
}

_configured = False


def setup_logging() -> None:
    """Call once at app startup (in main.py)."""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Noisy libraries can log URLs/headers, keep them quiet
    for noisy in ("httpx", "httpcore", "huggingface_hub", "urllib3", "PIL", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def _format_fields(fields: dict) -> str:
    parts = []
    for key, value in fields.items():
        if key not in ALLOWED_FIELDS or value is None:
            continue
        if key == "session_id":
            value = str(value)[:8]  # never log the full session id
        parts.append(f"{key}={value}")
    return " ".join(parts)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    """Example: log_event(logger, "analyze_done", status="ok", latency_ms=820)"""
    extra = _format_fields(fields)
    logger.log(level, f"{event} {extra}".strip())


def log_error(logger: logging.Logger, event: str, exc: Exception, **fields) -> None:
    """Logs only the exception TYPE. No message, no traceback.
    Pydantic and other errors can contain the user's input in their message."""
    fields["error_type"] = type(exc).__name__
    extra = _format_fields(fields)
    logger.error(f"{event} {extra}".strip())


@contextmanager
def timed():
    """Usage:
        with timed() as t:
            ...work...
        log_event(logger, "inference_done", latency_ms=t["latency_ms"])
    """
    result = {"latency_ms": 0}
    start = time.perf_counter()
    try:
        yield result
    finally:
        result["latency_ms"] = round((time.perf_counter() - start) * 1000)