from fastapi import APIRouter

from backend.config import settings
from backend.schemas.analyze import HealthResponse
from backend.services.model_service import model_service

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    loaded = model_service.is_loaded
    return HealthResponse(
        status="ok" if loaded else "degraded",
        app=settings.app_name,
        model_loaded=loaded,
    )