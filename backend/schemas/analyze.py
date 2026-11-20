import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.config import settings

# session ids are uuid4().hex (32 lowercase hex chars)
SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
# control characters (except tab/newline) are stripped from questions
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class QuestionInput(BaseModel):
    """Text fields that arrive with the image in the multipart form."""

    question: str
    session_id: Optional[str] = None

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = CONTROL_CHARS.sub("", value).strip()
        if len(value) < settings.min_question_length:
            raise ValueError(
                f"Question must be at least {settings.min_question_length} characters."
            )
        if len(value) > settings.max_question_length:
            raise ValueError(
                f"Question must be at most {settings.max_question_length} characters."
            )
        return value

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return None
        if not SESSION_ID_PATTERN.match(value):
            raise ValueError("Invalid session id.")
        return value


class AnalyzeResponse(BaseModel):
    status: Literal["ok"] = "ok"
    answer: str
    session_id: str
    latency_ms: int = Field(ge=0)


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error_code: str  # e.g. INVALID_QUESTION, IMAGE_TOO_LARGE, SESSION_EXPIRED
    message: str  # safe text, never contains user input
    retry: bool = False  # tells the browser to show the Retry button


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    app: str
    model_loaded: bool