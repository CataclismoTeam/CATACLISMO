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


class LuciaMeetingPointInput(BaseModel):
    """Punto de Encuentro explícito enviado por el usuario/operador o por el Frontend."""

    id: str | None = Field(default=None, description="Identificador opcional del Punto de Encuentro")
    name: str = Field(
        default="Punto de Encuentro",
        description="Nombre descriptivo del Punto de Encuentro (ej. 'Polideportivo Municipal', 'Cruce N-435')",
    )
    lon: float | None = Field(default=None, description="Longitud WGS84 del Punto de Encuentro")
    lat: float | None = Field(default=None, description="Latitud WGS84 del Punto de Encuentro")
    grid_rc: list[int] | None = Field(
        default=None,
        description="Coordenada local [fila, columna] (0..31) alternativa a lon/lat",
    )
    kind: str = Field(
        default="official_assembly_point",
        description="Categoría del Punto de Encuentro (ej. 'shelter', 'road_junction_assembly', 'heliport')",
    )
    capacity: int = Field(default=500, ge=1, description="Capacidad estimada de personas/animales")


class LuciaRouteRequest(BaseModel):
    """Petición interactiva desde el Frontend para calcular ruta segura hacia un Punto de Encuentro."""

    lon: float = Field(..., description="Longitud WGS84 de inicio (ej. -6.541)")
    lat: float = Field(..., description="Latitud WGS84 de inicio (ej. 37.452)")
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
    meeting_points: list[LuciaMeetingPointInput] | None = Field(
        default=None,
        description=(
            "Lista opcional de Puntos de Encuentro explícitos hacia los que dirigir la ruta. "
            "Si se omite, LUCIA utiliza los Puntos de Encuentro oficiales seguros de la zona."
        ),
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
    """Calcula en tiempo real una ruta GeoJSON desde `(lon, lat)` hacia el Punto de Encuentro más seguro."""
    if not os.path.exists(lucia_config.DEFAULT_CATA_PREDICTIONS_PATH):
        raise HTTPException(
            status_code=404,
            detail="No se encontró cata_predictions.json. Ejecuta primero CATA.",
        )
    custom_mps = (
        [mp.model_dump(exclude_none=True) for mp in req.meeting_points]
        if req.meeting_points
        else None
    )
    return compute_Interactive_route_from_lonlat(
        lon=req.lon,
        lat=req.lat,
        profile=req.profile,
        safe_fire_threshold=req.safe_fire_threshold,
        meeting_points=custom_mps,
    )


@app.get("/api/lucia/meeting-points")
async def get_lucia_meeting_points(
    zone_id: str | None = Query(default=None, description="Filtrar por zone_id de CATA"),
) -> dict:
    """Devuelve todos los Puntos de Encuentro (Meeting Points) activos en las zonas de LUCIA."""
    default_path = lucia_config.DEFAULT_GEOJSON_OUTPUT_PATH
    if os.path.exists(default_path):
        with open(default_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = generate_lucia_geojson_from_cata(output_geojson_path=None)

    mp_features = [
        feat
        for feat in data.get("features", [])
        if feat.get("properties", {}).get("feature_type") == "meeting_point"
        and (zone_id is None or feat.get("properties", {}).get("zone_id") == zone_id)
    ]
    return {
        "type": "FeatureCollection",
        "total_meeting_points": len(mp_features),
        "features": mp_features,
    }


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
