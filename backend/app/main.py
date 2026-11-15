"""Punto de entrada de la API: uvicorn app.main:app --reload"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import settings
from app.db import postgis_version
from app.juli import config as juli_config
from app.juli.chat import broadcast_proof_of_life_alerts_to_chat
from app.juli.coords import quadrant_subcoords_to_lonlat
from app.juli.main import juli_live_router, register_radio_event_hook
from app.juli.tracker import juli_tracker
from app.lucia import config as lucia_config
from app.ws import manager

_LOGGER = logging.getLogger(__name__)
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_STATUS_PATH = os.path.join(_APP_DIR, "continual", "artifacts", "live_nrt_status.json")


def _load_lucia_router():
    try:
        from app.lucia.router import (
            compute_Interactive_route_from_lonlat,
            generate_lucia_geojson_from_cata,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Recálculo neuronal LUCIA no disponible en este despliegue ligero "
                "(requiere dependencias opcionales [trainer])."
            ),
        ) from exc
    return compute_Interactive_route_from_lonlat, generate_lucia_geojson_from_cata


def _load_continual_engine():
    try:
        from app.continual import continual_engine
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Motor de aprendizaje continuo no disponible en este despliegue ligero "
                "(requiere dependencias opcionales [trainer])."
            ),
        ) from exc
    return continual_engine


def _load_live_nrt_runner():
    try:
        from app.live_nrt import run_live_nrt_cycle
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Pipeline live NRT no disponible en este despliegue ligero "
                "(requiere dependencias opcionales [trainer])."
            ),
        ) from exc
    return run_live_nrt_cycle


def _read_json_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_json_if_exists(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    return _read_json_file(path)


async def _broadcast_proof_of_life_events(events: list[dict]) -> None:
    """Emite por /ws y /ws/chat cualquier aviso nuevo o resolución de prueba de vida."""
    if not events:
        return
    await broadcast_proof_of_life_alerts_to_chat(events)
    if not manager.active:
        return
    for event in events:
        try:
            await manager.broadcast(event)
        except Exception as exc:
            _LOGGER.debug("Fallo enviando evento proof-of-life por WS: %s", exc)


async def _proof_of_life_monitor() -> None:
    """Supervisor periódico: avisa a Central y al escuadrón por inmovilidad o fuego."""
    while True:
        try:
            pol_events = juli_tracker.poll_proof_of_life_events()
            await _broadcast_proof_of_life_events(pol_events["events"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.debug("Error en ciclo monitor proof-of-life: %s", exc)
        await asyncio.sleep(juli_config.PROOF_OF_LIFE_CHECK_INTERVAL_S)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_proof_of_life_monitor())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="CATACLISMO API (Pipeline VALEN -> CATA -> LUCIA + Sistema Independiente JULI)",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(juli_live_router)


async def _broadcast_radio_event(event: dict) -> None:
    """Reenvía cambios de frecuencia/escuadrón del walkie-talkie al WebSocket `/ws`."""
    if not manager.active:
        return
    await manager.broadcast(event)


register_radio_event_hook(_broadcast_radio_event)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LuciaMeetingPointInput(BaseModel):
    """Punto de Encuentro explícito enviado por el usuario/operador o por el Frontend."""

    id: str | None = Field(
        default=None, description="Identificador opcional del Punto de Encuentro"
    )
    name: str = Field(
        default="Punto de Encuentro",
        description=(
            "Nombre descriptivo del Punto de Encuentro "
            "(ej. 'Polideportivo Municipal', 'Cruce N-435')"
        ),
    )
    lon: float | None = Field(default=None, description="Longitud WGS84 del Punto de Encuentro")
    lat: float | None = Field(default=None, description="Latitud WGS84 del Punto de Encuentro")
    cell_id: str | None = Field(
        default=None,
        description="Cuadrante 1000x1000m (ej. 'ES1K:L0:Y02209:X02996') alternativo a lon/lat",
    )
    quadrant_id: str | None = Field(
        default=None,
        description="Alias de cell_id en la cuadrícula unificada 1000x1000m",
    )
    grid_rc: list[int] | None = Field(
        default=None,
        description="Coordenada local [fila, columna] (0..31) alternativa a lon/lat",
    )
    kind: str = Field(
        default="official_assembly_point",
        description=(
            "Categoría del Punto de Encuentro (ej. 'shelter', 'road_junction_assembly', 'heliport')"
        ),
    )
    capacity: int = Field(default=500, ge=1, description="Capacidad estimada de personas/animales")


class LuciaRouteRequest(BaseModel):
    """Petición desde el Frontend para calcular ruta segura hacia un Punto de Encuentro."""

    lon: float | None = Field(
        default=None, description="Longitud WGS84 de inicio (opcional si se pasa quadrant_id)"
    )
    lat: float | None = Field(
        default=None, description="Latitud WGS84 de inicio (opcional si se pasa quadrant_id)"
    )
    quadrant_id: str | None = Field(
        default=None,
        description="Cuadrante de inicio 1000x1000m (ej. 'ES1K:L0:Y02209:X02996')",
    )
    offset_x_m: float | None = Field(
        default=None, ge=0.0, lt=1000.0, description="Metros al este dentro del cuadrante [0, 1000)"
    )
    offset_y_m: float | None = Field(
        default=None,
        ge=0.0,
        lt=1000.0,
        description="Metros al norte dentro del cuadrante [0, 1000)",
    )
    sub_x_norm: float | None = Field(
        default=None, ge=0.0, lt=1.0, description="Subcoordenada X normalizada [0, 1)"
    )
    sub_y_norm: float | None = Field(
        default=None, ge=0.0, lt=1.0, description="Subcoordenada Y normalizada [0, 1)"
    )
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
        description=(
            "Incluir polígonos 1kmx1km de zonas quemadas, quemándose y buffer del threshold"
        ),
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
    if is_default_query:
        cached = await asyncio.to_thread(_read_json_if_exists, default_path)
        if cached is not None:
            return cached

    if not await asyncio.to_thread(os.path.exists, lucia_config.DEFAULT_CATA_PREDICTIONS_PATH):
        raise HTTPException(
            status_code=404,
            detail="No se encontró cata_predictions.json. Ejecuta primero CATA.",
        )

    profiles_seq = ("human", "animal") if profile == "both" else (profile,)
    _, generate_lucia_geojson_from_cata = _load_lucia_router()
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
    """Calcula una ruta GeoJSON desde `(lon, lat)` hacia el Punto de Encuentro más seguro."""
    if not await asyncio.to_thread(os.path.exists, lucia_config.DEFAULT_CATA_PREDICTIONS_PATH):
        raise HTTPException(
            status_code=404,
            detail="No se encontró cata_predictions.json. Ejecuta primero CATA.",
        )
    lon, lat = req.lon, req.lat
    if (lon is None or lat is None) and req.quadrant_id:
        try:
            lon, lat = quadrant_subcoords_to_lonlat(
                quadrant_id=req.quadrant_id,
                offset_x_m=req.offset_x_m,
                offset_y_m=req.offset_y_m,
                sub_x_norm=req.sub_x_norm,
                sub_y_norm=req.sub_y_norm,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if lon is None or lat is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Se requiere (lon, lat) o quadrant_id (ES1K:L0:Y...:X...) para calcular la ruta."
            ),
        )
    custom_mps = (
        [mp.model_dump(exclude_none=True) for mp in req.meeting_points]
        if req.meeting_points
        else None
    )
    compute_interactive_route, _ = _load_lucia_router()
    return compute_interactive_route(
        lon=lon,
        lat=lat,
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
    cached_data = await asyncio.to_thread(_read_json_if_exists, default_path)
    if cached_data is not None:
        data = cached_data
    else:
        _, generate_lucia_geojson_from_cata = _load_lucia_router()
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
    data = await asyncio.to_thread(_read_json_if_exists, path)
    if data is None:
        raise HTTPException(status_code=404, detail="No se encontró cata_predictions.json.")
    return data


class ContinualFeedbackInput(BaseModel):
    """Feedback en vivo desde el terreno (First Responders / JULI) para calibrar CATA y LUCIA."""

    zone_or_block_id: str = Field(
        ...,
        description="ID de zona o bloque (ej. 'ES1K_block_138_187_2022-07-18 06:00' o '138_187')",
    )
    feedback_type: Literal["confirmed_fire", "false_alarm"] = Field(
        ...,
        description=(
            "'confirmed_fire' si hay fuego real no detectado; 'false_alarm' si es falsa alarma"
        ),
    )
    intensity: float = Field(default=1.0, ge=0.1, le=2.0, description="Peso del ajuste (0.1 a 2.0)")


@app.get("/api/continual/status")
async def get_continual_status() -> dict:
    """Devuelve el estado del motor de aprendizaje continuo recursivo de CATA y LUCIA."""
    continual_engine = _load_continual_engine()
    return continual_engine.state


@app.post("/api/continual/feedback")
async def post_continual_feedback(req: ContinualFeedbackInput) -> dict:
    """Aplica feedback directo desde terreno a la memoria recursiva sin reentrenar."""
    continual_engine = _load_continual_engine()
    res = continual_engine.register_field_feedback(
        block_or_zone_id=req.zone_or_block_id,
        feedback_type=req.feedback_type,
        intensity=req.intensity,
    )
    return {"status": "ok", **res, "continual_state": continual_engine.state}


@app.get("/api/live/status")
async def get_live_nrt_status() -> dict:
    """Devuelve el estado de la última consulta Near Real-Time a NASA FIRMS."""
    status = await asyncio.to_thread(_read_json_if_exists, LIVE_STATUS_PATH)
    if status is not None:
        return status
    return {
        "status": "idle",
        "firms_key_configured": bool(settings.firms_map_key or os.environ.get("FIRMS_MAP_KEY")),
    }


@app.post("/api/live/refresh")
async def trigger_live_nrt_refresh(days: int = Query(default=2, ge=1, le=10)) -> dict:
    """Descarga detecciones FIRMS NRT en directo, predice con CATA y actualiza rutas LUCIA."""
    run_live_nrt_cycle = _load_live_nrt_runner()
    try:
        res = run_live_nrt_cycle(days=days)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if res.get("status") == "updated_live":
        await manager.broadcast({"event": "live_nrt_updated", **res})
    return res


# ==============================================================================
# JULI — Sistema independiente de control de operarios y equipos en el terreno
# ==============================================================================


class JuliTeamInput(BaseModel):
    """Petición para crear o actualizar un equipo de operarios en JULI."""

    team_id: str = Field(..., description="ID único del equipo (ej. 'team_brif_huelva')")
    name: str = Field(..., description="Nombre del equipo (ej. 'BRIF-A Huelva — Cuadrilla 1')")
    unit_code: str = Field(default="BRIF-1", description="Código táctico corto (ej. 'BRIF-HU-01')")
    vehicle_type: str = Field(default="Autobomba 4x4", description="Vehículo o dotación del equipo")
    zone_assigned: str = Field(default="Sector General", description="Sector o cuadrante asignado")
    color: str | None = Field(
        default=None, description="Color hexadecimal opcional (ej. '#06b6d4')"
    )
    radio_channel: str = Field(default="VHF-01", description="Canal de radio asignado")


class JuliOperatorInput(BaseModel):
    """Petición para alta o actualización de operario por WGS84 o cuadrante y subcoordenadas."""

    operator_id: str | None = Field(
        default=None,
        description="ID del operario (si se omite, JULI genera uno automáticamente)",
    )
    name: str = Field(..., description="Nombre y apellidos del operario")
    team_id: str = Field(..., description="ID del equipo al que pertenece")
    lon: float | None = Field(
        default=None, description="Longitud WGS84 absoluta (opcional si se pasa quadrant_id)"
    )
    lat: float | None = Field(
        default=None, description="Latitud WGS84 absoluta (opcional si se pasa quadrant_id)"
    )
    quadrant_id: str | None = Field(
        default=None, description="Cuadrante 1000x1000m (ej. 'ES1K:L0:Y02209:X02996')"
    )
    offset_x_m: float | None = Field(
        default=None, ge=0.0, lt=1000.0, description="Metros al este dentro del cuadrante [0, 1000)"
    )
    offset_y_m: float | None = Field(
        default=None,
        ge=0.0,
        lt=1000.0,
        description="Metros al norte dentro del cuadrante [0, 1000)",
    )
    sub_x_norm: float | None = Field(
        default=None, ge=0.0, lt=1.0, description="Subcoordenada X normalizada [0, 1)"
    )
    sub_y_norm: float | None = Field(
        default=None, ge=0.0, lt=1.0, description="Subcoordenada Y normalizada [0, 1)"
    )
    elevation_m: float = Field(default=0.0, description="Altitud sobre el nivel del mar (m)")
    role: juli_config.OperatorRole = Field(
        default="brigadista",
        description=(
            "Rol ('jefe_cuadrilla', 'brigadista', 'conductor_autobomba', "
            "'sanitario', 'piloto_dron', 'coordinador')"
        ),
    )
    status: juli_config.OperatorStatus = Field(
        default="en_terreno",
        description=(
            "Estado operativo ('en_terreno', 'en_ruta', 'en_descanso', 'alerta', 'inactivo')"
        ),
    )
    callsign: str | None = Field(default=None, description="Indicativo de radio (ej. 'ALFA-1')")
    battery_pct: int = Field(default=100, ge=0, le=100, description="Batería del emisor GPS (%)")
    heart_rate_bpm: int | None = Field(default=None, description="Pulso cardíaco opcional (bpm)")


class JuliLocationPatchInput(BaseModel):
    """Actualización rápida de posición por WGS84 o subcoordenadas en el cuadrante 1000x1000m."""

    lon: float | None = Field(default=None, description="Nueva longitud WGS84 absoluta")
    lat: float | None = Field(default=None, description="Nueva latitud WGS84 absoluta")
    quadrant_id: str | None = Field(default=None, description="Nuevo cuadrante ES1K 1000x1000m")
    offset_x_m: float | None = Field(
        default=None, ge=0.0, lt=1000.0, description="Metros al este dentro del cuadrante [0, 1000)"
    )
    offset_y_m: float | None = Field(
        default=None,
        ge=0.0,
        lt=1000.0,
        description="Metros al norte dentro del cuadrante [0, 1000)",
    )
    sub_x_norm: float | None = Field(
        default=None, ge=0.0, lt=1.0, description="Subcoordenada X normalizada [0, 1)"
    )
    sub_y_norm: float | None = Field(
        default=None, ge=0.0, lt=1.0, description="Subcoordenada Y normalizada [0, 1)"
    )
    elevation_m: float | None = Field(default=None, description="Nueva altitud (m)")
    status: juli_config.OperatorStatus | None = Field(
        default=None, description="Nuevo estado operativo"
    )
    battery_pct: int | None = Field(default=None, ge=0, le=100, description="Nivel de batería (%)")
    heart_rate_bpm: int | None = Field(default=None, description="Pulso cardíaco (bpm)")
    team_id: str | None = Field(default=None, description="Cambio opcional de equipo")


@app.get("/api/juli/geojson")
async def get_juli_geojson(
    team_id: str | None = Query(
        default=None, description="Filtrar por ID de equipo (ej. 'team_brif_huelva')"
    ),
    status: Annotated[
        juli_config.OperatorStatus | None,
        Query(
            description=(
                "Filtrar operarios por estado ('active', 'en_route', 'resting', 'alert', 'offline')"
            ),
        ),
    ] = None,
    include_team_features: bool = Query(
        default=True,
        description=(
            "Incluir centroide y líneas de formación del equipo "
            "además de los puntos de cada persona"
        ),
    ),
) -> dict:
    """Devuelve el GeoJSON (`FeatureCollection`, `EPSG:4326`) de JULI con operarios y equipos."""
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
        unit_code=req.unit_code,
        vehicle_type=req.vehicle_type,
        zone_assigned=req.zone_assigned,
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
    """Añade o actualiza una persona en un equipo de JULI y devuelve el GeoJSON actualizado."""
    try:
        op = juli_tracker.upsert_operator(
            operator_id=req.operator_id,
            name=req.name,
            team_id=req.team_id,
            lon=req.lon,
            lat=req.lat,
            elevation_m=req.elevation_m,
            role=req.role,
            status=req.status,
            callsign=req.callsign or "",
            battery_pct=req.battery_pct,
            heart_rate_bpm=req.heart_rate_bpm,
            quadrant_id=req.quadrant_id,
            offset_x_m=req.offset_x_m,
            offset_y_m=req.offset_y_m,
            sub_x_norm=req.sub_x_norm,
            sub_y_norm=req.sub_y_norm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    """Actualiza en tiempo real la posición GPS/subcoordenadas de un operario y emite por WS."""
    try:
        op = juli_tracker.update_operator_location(
            operator_id=operator_id,
            lon=req.lon,
            lat=req.lat,
            elevation_m=req.elevation_m,
            status=req.status,
            battery_pct=req.battery_pct,
            heart_rate_bpm=req.heart_rate_bpm,
            team_id=req.team_id,
            quadrant_id=req.quadrant_id,
            offset_x_m=req.offset_x_m,
            offset_y_m=req.offset_y_m,
            sub_x_norm=req.sub_x_norm,
            sub_y_norm=req.sub_y_norm,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    geojson_payload = juli_tracker.export_geojson()
    await manager.broadcast(
        {
            "event": "juli_operator_moved",
            "operator_id": op.operator_id,
            "team_id": op.team_id,
            "geojson": geojson_payload,
        }
    )
    pol_events = juli_tracker.poll_proof_of_life_events()
    await _broadcast_proof_of_life_events(pol_events["events"])
    return {
        "status": "ok",
        "operator": op.to_dict(),
        "proof_of_life_events": pol_events["events"],
        "geojson": geojson_payload,
    }


@app.post("/api/juli/proof-of-life/check")
async def check_juli_proof_of_life(
    immobile_seconds: int = Query(
        default=juli_config.PROOF_OF_LIFE_IMMOBILE_SECONDS,
        ge=1,
    ),
) -> dict:
    """Ejecuta comprobación inmediata de prueba de vida y difunde alertas nuevas por WebSocket."""
    pol_events = juli_tracker.poll_proof_of_life_events(immobile_seconds=immobile_seconds)
    await _broadcast_proof_of_life_events(pol_events["events"])
    return {
        "status": "ok",
        "algorithm": juli_config.ALGORITHM_NAME,
        **pol_events,
    }


@app.delete("/api/juli/operators/{operator_id}")
async def delete_juli_operator(operator_id: str) -> dict:
    """Da de baja a un operario del terreno y actualiza el GeoJSON."""
    removed = juli_tracker.remove_operator(operator_id)
    if not removed:
        raise HTTPException(
            status_code=404, detail=f"No existe el operario '{operator_id}' en JULI."
        )
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
