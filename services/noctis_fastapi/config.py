from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Runtime configuration for the FastAPI gateway."""

    django_settings_module: str = Field(
        default="noctis_pro.settings",
        description="Django settings module to bootstrap before model access",
    )
    api_key_header: str = Field(
        default="X-Noctis-Api-Key",
        description="Header used for service-to-service authentication",
    )
    api_key: str = Field(
        default="change-me",
        env="NOCTIS_FASTAPI_TOKEN",
        description="Shared secret for calling the gateway",
    )
    storage_root: Path = Field(
        default=Path('/workspace/media/dicom/received'),
        description="Location where the Rust receiver drops raw DICOM files",
    )
    thumbnail_root: Path = Field(
        default=Path('/workspace/media/dicom/thumbnails'),
        description="Directory used for generated thumbnails",
    )

    class Config:
        env_prefix = "NOCTIS_FASTAPI_"
        env_file = '.env'


@lru_cache
def get_settings() -> Settings:
    return Settings()
