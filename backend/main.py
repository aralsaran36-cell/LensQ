import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import BASE_DIR, settings
from backend.routes import analyze, health
from backend.schemas.analyze import ErrorResponse
from backend.services.model_service import model_service
from backend.services.session_store import session_store
from backend.utils.logger import get_logger, log_error, log_event, setup_logging
from backend.utils.validators import AppError

setup_logging()
logger = get_logger(__name__)

FRONTEND_DIR = BASE_DIR / "frontend"


async def _load_model_in_background() -> None:
    """Server starts immediately. /health shows 'degraded' until the model is ready."""
    try:
        await asyncio.to_thread(model_service.load)
    except Exception as exc:
        log_error(logger, "model_load_failed", exc, model_id=settings.model_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event(logger, "app_starting", status="ok")
    session_store.start_cleanup()
    load_task = asyncio.create_task(_load_model_in_background())
    yield
    load_task.cancel()
    await session_store.stop_cleanup()  # wipes every session image from memory
    model_service.unload()
    log_event(logger, "app_stopped", status="ok")


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.debug else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


def _error_json(status_code: int, error_code: str, message: str, retry: bool = False) -> JSONResponse:
    body = ErrorResponse(error_code=error_code, message=message, retry=retry)
    return JSONResponse(status_code=status_code, content=body.model_dump())


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    log_event(
        logger, "request_rejected",
        status="error", status_code=exc.status_code, error_code=exc.error_code,
    )
    return _error_json(exc.status_code, exc.error_code, exc.message, exc.retry)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default response echoes the user's input back. We never do that.
    log_event(logger, "request_invalid", status="error", status_code=400, error_code="INVALID_REQUEST")
    return _error_json(400, "INVALID_REQUEST", "Invalid request.")


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log_error(logger, "unexpected_error", exc, status_code=500)  # type only, no message
    return _error_json(500, "INTERNAL_ERROR", "Something went wrong. Please try again.", retry=True)


app.include_router(health.router)
app.include_router(analyze.router)

# Frontend is served from the same origin (no CORS problems). Mounted last,
# so /health and /analyze are matched first.
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")