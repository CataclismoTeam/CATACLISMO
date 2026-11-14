"""Punto de entrada de la API: uvicorn app.main:app --reload"""

import json
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import settings
from app.db import postgis_version
from app.lucia import config as lucia_config
from app.lucia.router import (
    compute_Interactive_route_from_lonlat,
    generate_lucia_geojson_from_cata,
)
from app.ws import manager

app = FastAPI(
    title="CATACLISMO API (Pipeline VALEN -> CATA -> LUCIA)",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LuciaRouteRequest(BaseModel):
    """Petición interactiva desde el Frontend para calcular ruta segura desde un punto GPS."""

    lon: float = Field(..., description="Longitud WGS84 (ej. -6.541)")
    lat: float = Field(..., description="Latitud WGS84 (ej. 37.452)")
    profile: Literal["human", "animal"] = Field(
        default="human",
        description="Perfil de evacuación: 'human' (personas) o 'animal' (fauna/ganado)",
    )
    safe_fire_threshold: float = Field(
        default=lucia_config.SAFE_FIRE_THRESHOLD,
        ge=0.05,
        le=0.95,
        description="Threshold seguro al fuego para zonas sin quemar (por defecto 0.25)",
    )


@app.get("/health")
async def health() -> dict:
    """Estado de la API y de la base de datos (no falla si la BD está caída)."""
    version = await postgis_version()
    return {
        "status": "ok",
        "pipeline": list(lucia_config.PIPELINE_CHAIN),
        "database": "ok" if version else "unavailable",
        "postgis": version,
    }


@app.get("/api/lucia/routes")
async def get_lucia_routes(
    zone_id: str | None = Query(default=None, description="Filtrar por zone_id de CATA"),
    profile: Literal["human", "animal", "both"] = Query(
        default="both", description="Filtrar rutas por perfil: 'human', 'animal' o 'both'"
    ),
    safe_fire_threshold: float = Query(
        default=lucia_config.SAFE_FIRE_THRESHOLD,
        ge=0.05,
        le=0.95,
        description="Threshold seguro al fuego para zonas sin quemar",
    ),
    include_fire_polygons: bool = Query(
        default=True,
        description="Incluir polígonos 1kmx1km de zonas quemadas, quemándose y buffer del threshold",
    ),
) -> dict:
    """Devuelve el GeoJSON (`FeatureCollection`, WGS84) de rutas de evacuación seguras de LUCIA.

    Si no se aplican filtros personalizados y existe `lucia_routes.geojson` precalculado,
    lo sirve directamente; si se cambia `safe_fire_threshold`, `zone_id` o `profile`,
    recalcula al vuelo desde `cata_predictions.json`.
    """
    default_path = lucia_config.DEFAULT_GEOJSON_OUTPUT_PATH
    is_default_query = (
        zone_id is None
        and profile == "both"
        and abs(safe_fire_threshold - lucia_config.SAFE_FIRE_THRESHOLD) < 1e-6
        and include_fire_polygons
    )
    if is_default_query and os.path.exists(default_path):
        with open(default_path, encoding="utf-8") as f:
            return json.load(f)

    if not os.path.exists(lucia_config.DEFAULT_CATA_PREDICTIONS_PATH):
        raise HTTPException(
            status_code=404,
            detail="No se encontró cata_predictions.json. Ejecuta primero CATA.",
        )

    profiles_seq = ("human", "animal") if profile == "both" else (profile,)
    return generate_lucia_geojson_from_cata(
        cata_predictions_path=lucia_config.DEFAULT_CATA_PREDICTIONS_PATH,
        output_geojson_path=None,
        model_path=lucia_config.DEFAULT_MODEL_PATH,
        safe_fire_threshold=safe_fire_threshold,
        profiles=profiles_seq,
        zone_filter=zone_id,
        include_fire_polygons=include_fire_polygons,
    )


@app.post("/api/lucia/route")
async def compute_lucia_interactive_route(req: LuciaRouteRequest) -> dict:
    """Calcula en tiempo real una ruta GeoJSON desde `(lon, lat)` hacia la zona libre de peligro más cercana."""
    if not os.path.exists(lucia_config.DEFAULT_CATA_PREDICTIONS_PATH):
        raise HTTPException(
            status_code=404,
            detail="No se encontró cata_predictions.json. Ejecuta primero CATA.",
        )
    return compute_Interactive_route_from_lonlat(
        lon=req.lon,
        lat=req.lat,
        profile=req.profile,
        safe_fire_threshold=req.safe_fire_threshold,
    )


@app.get("/api/cata/predictions")
async def get_cata_predictions() -> dict:
    """Devuelve el JSON de predicciones de CATA (`cata_predictions.json`) que alimenta a LUCIA."""
    path = lucia_config.DEFAULT_CATA_PREDICTIONS_PATH
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No se encontró cata_predictions.json.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Canal en tiempo real: de momento reenvía a todos lo que recibe."""
    await manager.connect(websocket)
    try:
        while True:
            await manager.broadcast(await websocket.receive_json())
    except WebSocketDisconnect:
        manager.disconnect(websocket)
