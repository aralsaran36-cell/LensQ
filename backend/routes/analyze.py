from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from backend.schemas.analyze import SESSION_ID_PATTERN, AnalyzeResponse, ErrorResponse
from backend.services.image_service import prepare_image
from backend.services.model_service import model_service
from backend.services.session_store import session_store
from backend.utils.logger import get_logger, log_event, timed
from backend.utils.validators import (
    AppError,
    parse_question,
    read_and_validate_image,
)

logger = get_logger(__name__)
router = APIRouter()

ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    410: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    415: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@router.post("/analyze", response_model=AnalyzeResponse, responses=ERROR_RESPONSES)
async def analyze(
    question: str = Form(""),
    session_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
) -> AnalyzeResponse:
    """
    First question: send image + question.
    Follow-up questions: send question + session_id only (no image).
    New image: send image + question + session_id (old image is replaced).
    """
    with timed() as t:
        data = parse_question(question, session_id)

        if image is not None:
            validated = await read_and_validate_image(image)
            prepared = await prepare_image(validated)
            # Stored BEFORE inference, so "Retry" works without re-uploading
            session = await session_store.create_or_replace(
                prepared.data, prepared.mime, data.session_id
            )
        else:
            session = await session_store.get(data.session_id)
            if session is None:
                raise AppError(
                    410,
                    "SESSION_EXPIRED",
                    "Your session expired. Please upload the image again.",
                )

        answer = await model_service.answer(session.image_bytes, data.question)

    log_event(
        logger,
        "analyze_done",
        status="ok",
        session_id=session.session_id,
        image_size_kb=round(len(session.image_bytes) / 1024),
        latency_ms=t["latency_ms"],
    )
    return AnalyzeResponse(
        answer=answer, session_id=session.session_id, latency_ms=t["latency_ms"]
    )


@router.post("/session/end")
async def end_session(session_id: Optional[str] = Form(None)) -> dict:
    """Deletes the image from memory. POST + form, so the browser can call it
    with navigator.sendBeacon when the tab closes."""
    if not session_id or not SESSION_ID_PATTERN.match(session_id):
        raise AppError(400, "INVALID_SESSION", "Invalid session id.")
    await session_store.delete(session_id)
    log_event(logger, "session_ended", status="ok", session_id=session_id)
    return {"status": "ok"}