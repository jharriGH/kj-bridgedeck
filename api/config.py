"""Settings loaded from environment. Cached singleton via lru_cache."""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str
    SUPABASE_ANON_KEY: Optional[str] = None

    BRAIN_API_URL: str = "https://jim-brain-production.up.railway.app"
    BRAIN_KEY: str

    BRIDGEDECK_ADMIN_KEY: str

    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None

    WATCHER_HOST: Optional[str] = None
    MACHINE_ID: str = "render-cloud"

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,https://bridgedeck.pages.dev"

    VERSION: str = "0.1.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
