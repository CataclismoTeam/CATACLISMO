"""Configuración leída de variables de entorno (o de backend/.env en local)."""

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Release con los resultados del ciclo en vivo que publica GitHub Actions (live-nrt.yml)
LIVE_DATA_RELEASE = "https://github.com/CataclismoTeam/CATACLISMO/releases/download/live-data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://cataclismo:cataclismo@localhost:5432/cataclismo"
    # Orígenes del frontend con permiso para llamar a la API (separados por comas)
    cors_origins: str = (
        "http://localhost:5173,http://localhost:4173,https://cataclismoteam.github.io"
    )
    # Clave de NASA FIRMS para ingesta Near Real-Time (NRT)
    firms_map_key: str = ""
    live_nrt_interval_sec: int = 0  # >0 activa auto-refresco periódico en segundo plano
    # Release con los resultados del ciclo en vivo de GitHub Actions ("" = desactivado).
    # En Render (que define RENDER) se activa sola; en local y en los tests, no.
    live_data_url: str = Field(
        default_factory=lambda: LIVE_DATA_RELEASE if os.environ.get("RENDER") else ""
    )
    live_data_interval_sec: int = 600

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
