"""Conexión asíncrona a PostgreSQL + PostGIS."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings

engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)


async def postgis_version() -> str | None:
    """Versión de PostGIS, o None si la base de datos no responde."""
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text("SELECT postgis_version()"))).scalar_one()
    except Exception:
        return None
