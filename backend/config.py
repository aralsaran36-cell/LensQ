from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),  # allows fields named model_*
    )

    # App
    app_name: str = "LensQ"
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:8000"  # comma separated

    # Image limits
    max_file_size_mb: int = 5
    max_image_dimension: int = 2048  # px, longest side
    allowed_image_types: str = "image/jpeg,image/png,image/webp,image/heic"

    # Question limits
    min_question_length: int = 3
    max_question_length: int = 500

    # Session
    session_ttl_seconds: int = 600  # 10 min idle
    session_cleanup_interval_seconds: int = 60

    # Model
    model_id: str = "LiquidAI/LFM3-Omni-2B"
    model_device: str = "auto"  # auto / cpu / cuda / mps
    max_new_tokens: int = 256
    max_concurrent_inference: int = 1
    model_backend: Literal["mock", "transformers", "llamacpp"] = "transformers"  # mock = dev, transformers = GPU server, llamacpp = local GGUF
    llamacpp_base_url: str = "http://127.0.0.1:8080"
    llamacpp_timeout_seconds: int = 100  # keep below the 120 s browser/nginx timeout

    # Derived values
    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def allowed_image_types_list(self) -> list[str]:
        return [t.strip().lower() for t in self.allowed_image_types.split(",") if t.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()