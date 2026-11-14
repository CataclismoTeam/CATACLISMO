"""Configuración leída de variables de entorno (o de backend/.env en local)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://cataclismo:cataclismo@localhost:5432/cataclismo"
    # Orígenes del frontend con permiso para llamar a la API (separados por comas)
    cors_origins: str = "http://localhost:5173,https://celestedlc.github.io"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
