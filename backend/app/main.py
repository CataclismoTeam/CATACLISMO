"""Punto de entrada de la API: uvicorn app.main:app --reload"""

import json
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import settings
from app.db import postgis_version
from app.juli import config as juli_config
from app.juli.main import juli_live_router
from app.juli.tracker import juli_tracker
from app.lucia import config as lucia_config
from app.lucia.router import (
    compute_Interactive_route_from_lonlat,
    generate_lucia_geojson_from_cata,
)
from app.ws import manager

app = FastAPI(
    title="CATACLISMO API (Pipeline VALEN -> CATA -> LUCIA + Sistema Independiente JULI)",
    version="0.1.0",
)

app.include_router(juli_live_router)

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


# ==============================================================================
# JULI — Sistema independiente de control de operarios y equipos en el terreno
# ==============================================================================


class JuliTeamInput(BaseModel):
    """Petición para crear o actualizar un equipo de operarios en JULI."""

    team_id: str = Field(..., description="ID único del equipo (ej. 'team_brif_huelva')")
    name: str = Field(..., description="Nombre del equipo (ej. 'BRIF-A Huelva — Cuadrilla 1')")
    code: str = Field(default="BRIF-1", description="Código táctico corto (ej. 'BRIF-H1')")
    sector: str = Field(default="Sector General", description="Sector asignado en el terreno")
    color: str | None = Field(default=None, description="Color hexadecimal opcional (ej. '#3B82F6')")
    radio_channel: str = Field(default="CH-01", description="Canal de radio asignado")


class JuliOperatorInput(BaseModel):
    """Petición para dar de alta o actualizar una persona/operario dentro de un equipo en JULI."""

    operator_id: str | None = Field(
        default=None,
        description="ID del operario (si se omite, JULI genera uno automáticamente)",
    )
    name: str = Field(..., description="Nombre y apellidos del operario")
    team_id: str = Field(..., description="ID del equipo al que pertenece")
    lon: float = Field(..., description="Longitud WGS84 en el terreno (ej. -6.8245)")
    lat: float = Field(..., description="Latitud WGS84 en el terreno (ej. 37.2412)")
    elevation_m: float = Field(default=0.0, description="Altitud sobre el nivel del mar (m)")
    role: juli_config.OperatorRole = Field(
        default="brigadista",
        description="Rol en el equipo ('capataz', 'brigadista', 'conductor_autobomba', 'sanitario', 'observador', 'coordinador')",
    )
    status: juli_config.OperatorStatus = Field(
        default="active",
        description="Estado operativo ('active', 'en_route', 'resting', 'alert', 'offline')",
    )
    callsign: str | None = Field(default=None, description="Indicativo de radio (ej. 'BRIF-H1-05')")
    battery_pct: int = Field(default=100, ge=0, le=100, description="Batería del emisor GPS (%)")
    heart_rate_bpm: int | None = Field(default=None, description="Pulso cardíaco opcional (bpm)")
    assigned_task: str = Field(
        default="Operación en terreno",
        description="Tarea actual asignada en el terreno",
    )


class JuliLocationPatchInput(BaseModel):
    """Actualización rápida de posición GPS/telemetría de un operario en el terreno."""

    lon: float = Field(..., description="Nueva longitud WGS84")
    lat: float = Field(..., description="Nueva latitud WGS84")
    elevation_m: float | None = Field(default=None, description="Nueva altitud (m)")
    status: juli_config.OperatorStatus | None = Field(default=None, description="Nuevo estado operativo")
    battery_pct: int | None = Field(default=None, ge=0, le=100, description="Nivel de batería (%)")
    heart_rate_bpm: int | None = Field(default=None, description="Pulso cardíaco (bpm)")
    assigned_task: str | None = Field(default=None, description="Nueva tarea asignada")
    team_id: str | None = Field(default=None, description="Cambio opcional de equipo")


@app.get("/api/juli/geojson")
async def get_juli_geojson(
    team_id: str | None = Query(default=None, description="Filtrar por ID de equipo (ej. 'team_brif_huelva')"),
    status: juli_config.OperatorStatus | None = Query(
        default=None, description="Filtrar operarios por estado ('active', 'en_route', 'resting', 'alert', 'offline')"
    ),
    include_team_features: bool = Query(
        default=True,
        description="Incluir centroide y líneas de formación del equipo además de los puntos de cada persona",
    ),
) -> dict:
    """Devuelve el GeoJSON (`FeatureCollection`, `EPSG:4326`) de JULI con los operarios y equipos en el terreno."""
    return juli_tracker.build_geojson(
        team_filter=team_id,
        status_filter=status,
        include_team_features=include_team_features,
    )


@app.get("/api/juli/teams")
async def get_juli_teams() -> dict:
    """Devuelve el listado estructurado de equipos y sus personas en el terreno."""
    return {
        "algorithm": juli_config.ALGORITHM_NAME,
        "independent_from_pipeline": True,
        "teams": juli_tracker.list_teams_with_members(),
    }


@app.post("/api/juli/teams")
async def upsert_juli_team(req: JuliTeamInput) -> dict:
    """Crea o actualiza un equipo en JULI y devuelve el GeoJSON actualizado."""
    team = juli_tracker.upsert_team(
        team_id=req.team_id,
        name=req.name,
        code=req.code,
        sector=req.sector,
        color=req.color,
        radio_channel=req.radio_channel,
    )
    geojson_payload = juli_tracker.export_geojson()
    return {
        "status": "ok",
        "team": team.to_dict(),
        "geojson": geojson_payload,
    }


@app.post("/api/juli/operators")
async def upsert_juli_operator(req: JuliOperatorInput) -> dict:
    """Añade o actualiza una persona dentro de un equipo en JULI y devuelve el GeoJSON actualizado."""
    op = juli_tracker.upsert_operator(
        operator_id=req.operator_id,
        name=req.name,
        team_id=req.team_id,
        lon=req.lon,
        lat=req.lat,
        elevation_m=req.elevation_m,
        role=req.role,
        status=req.status,
        callsign=req.callsign,
        battery_pct=req.battery_pct,
        heart_rate_bpm=req.heart_rate_bpm,
        assigned_task=req.assigned_task,
    )
    geojson_payload = juli_tracker.export_geojson()
    await manager.broadcast(
        {
            "event": "juli_operator_upserted",
            "operator_id": op.operator_id,
            "team_id": op.team_id,
            "geojson": geojson_payload,
        }
    )
    return {
        "status": "ok",
        "operator": op.to_dict(),
        "geojson": geojson_payload,
    }


@app.patch("/api/juli/operators/{operator_id}/location")
async def update_juli_operator_location(operator_id: str, req: JuliLocationPatchInput) -> dict:
    """Actualiza en tiempo real la posición GPS/estado de un operario y emite el GeoJSON por WebSocket."""
    try:
        op = juli_tracker.update_operator_location(
            operator_id=operator_id,
            lon=req.lon,
            lat=req.lat,
            elevation_m=req.elevation_m,
            status=req.status,
            battery_pct=req.battery_pct,
            heart_rate_bpm=req.heart_rate_bpm,
            assigned_task=req.assigned_task,
            team_id=req.team_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    geojson_payload = juli_tracker.export_geojson()
    await manager.broadcast(
        {
            "event": "juli_operator_moved",
            "operator_id": op.operator_id,
            "team_id": op.team_id,
            "geojson": geojson_payload,
        }
    )
    return {
        "status": "ok",
        "operator": op.to_dict(),
        "geojson": geojson_payload,
    }


@app.delete("/api/juli/operators/{operator_id}")
async def delete_juli_operator(operator_id: str) -> dict:
    """Da de baja a un operario del terreno y actualiza el GeoJSON."""
    removed = juli_tracker.remove_operator(operator_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No existe el operario '{operator_id}' en JULI.")
    geojson_payload = juli_tracker.export_geojson()
    return {
        "status": "ok",
        "removed_operator_id": operator_id,
        "geojson": geojson_payload,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Canal en tiempo real: de momento reenvía a todos lo que recibe."""
    await manager.connect(websocket)
    try:
        while True:
            await manager.broadcast(await websocket.receive_json())
    except WebSocketDisconnect:
        manager.disconnect(websocket)
