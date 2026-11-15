"""JULI — Backend en tiempo real (FastAPI + WebSocket) para tracking GPS de First Responders.

Unifica en un mismo módulo:
  1. Simulador GPS/biométrico en tiempo real (`GET /api/units`, `POST /api/units/{id}/sos`,
     `POST /api/units/sync-fire`, `WS /ws/tracking`) desplegado sobre el perímetro real
     del incendio predicho por CATA (`cata_predictions.json`).
  2. Sincronización directa con `juli_tracker` (`tracker.py`), manteniendo los equipos,
     operarios, centroides, líneas de formación y exportación GeoJSON (`EPSG:4326`).

Ejecución standalone (desde `backend/app/juli/`):
    uvicorn main:app --reload --host 0.0.0.0 --port 8001

O integrado en la API principal (desde `backend/`):
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from . import config as juli_config
    from .tracker import juli_tracker
except ImportError:  # Ejecución standalone desde backend/app/juli/
    import config as juli_config
    from tracker import juli_tracker

# ---------------------------------------------------------------------------
# Modelos de datos y rutas
# ---------------------------------------------------------------------------

UnitRole = Literal["paramédico", "bombero", "dron"]
UnitStatus = Literal["activo", "en_camino", "sos"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CATA_PREDICTIONS_PATH = os.path.abspath(
    os.path.join(BASE_DIR, "..", "cata", "artifacts", "predictions", "cata_predictions.json")
)

LIVE_TEAM_ID = "team_first_response_live"
_ROLE_TO_TRACKER_ROLE = {
    "bombero": "brigadista",
    "paramédico": "sanitario",
    "dron": "observador",
}
_STATUS_TO_TRACKER_STATUS = {
    "activo": "active",
    "en_camino": "en_route",
    "sos": "alert",
}


class RescueUnit(BaseModel):
    """Representa una unidad de emergencias desplegada en el perímetro del incendio."""

    id: str
    role: UnitRole
    lat: float
    lon: float
    status: UnitStatus
    battery: int
    heart_rate: int
    zone_id: str = "fire_zone"
    anchor_lat: float = 0.0  # Centro táctico asignado en el perímetro
    anchor_lon: float = 0.0
    heading_deg: float = 0.0


# ---------------------------------------------------------------------------
# Aplicación FastAPI + Router compartido (usable standalone o en app.main)
# ---------------------------------------------------------------------------

app = FastAPI(
    title="JULI — First Response Team Live GPS Tracking",
    description="Simulador GPS en tiempo real (REST + WebSocket + GeoJSON) en zonas de incendio.",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

juli_live_router = APIRouter(tags=["juli-live"])

STATUS_COLORS: dict[str, str] = {
    "activo": "#10B981",
    "en_camino": "#F59E0B",
    "sos": "#EF4444",
}


# ---------------------------------------------------------------------------
# Despliegue táctico sobre zonas reales de incendio (`cata_predictions.json`)
# ---------------------------------------------------------------------------


def _load_fire_deployment_anchors(
    cata_path: str = DEFAULT_CATA_PREDICTIONS_PATH,
) -> tuple[str, list[tuple[float, float]]]:
    """Extrae coordenadas tácticas reales alrededor del frente de fuego de CATA."""
    fallback_zone = "ES1K_losacio_fallback"
    fallback_center = (41.718502, -5.990955)

    if os.path.exists(cata_path):
        try:
            with open(cata_path, encoding="utf-8") as f:
                data = json.load(f)
            cells = data.get("active_and_predicted_cells") or []
            zones = data.get("zones") or []
            if cells:
                primary_zone = (
                    str(zones[0].get("zone_id"))
                    if zones
                    else str(cells[0].get("zone_id", fallback_zone))
                )
                zone_cells = [c for c in cells if str(c.get("zone_id")) == primary_zone] or cells

                hot_cells = [
                    c
                    for c in zone_cells
                    if c.get("quadrant_label") in ("PREDICTED_FIRE", "CONFIRMED_AND_CONTINUES")
                    and isinstance(c.get("centroid_lonlat"), list)
                    and len(c["centroid_lonlat"]) >= 2
                ] or [
                    c
                    for c in zone_cells
                    if isinstance(c.get("centroid_lonlat"), list)
                    and len(c["centroid_lonlat"]) >= 2
                ]

                if hot_cells:
                    south_cell = min(hot_cells, key=lambda c: float(c["centroid_lonlat"][1]))
                    east_cell = max(hot_cells, key=lambda c: float(c["centroid_lonlat"][0]))
                    head_cell = max(
                        hot_cells,
                        key=lambda c: float(c.get("fire_probability_t1", 0.0)),
                    )

                    b_lon, b_lat = map(float, south_cell["centroid_lonlat"][:2])
                    p_lon, p_lat = map(float, east_cell["centroid_lonlat"][:2])
                    d_lon, d_lat = map(float, head_cell["centroid_lonlat"][:2])

                    return primary_zone, [
                        (b_lat - 0.0055, b_lon - 0.0035),
                        (p_lat + 0.0085, p_lon + 0.0110),
                        (d_lat + 0.0015, d_lon - 0.0015),
                    ]
        except Exception:
            pass

    f_lat, f_lon = fallback_center
    return fallback_zone, [
        (f_lat - 0.0065, f_lon - 0.0040),
        (f_lat + 0.0095, f_lon + 0.0120),
        (f_lat + 0.0010, f_lon - 0.0015),
    ]


def _sync_units_to_tracker(units: dict[str, RescueUnit], persist: bool = False) -> None:
    """Mantiene sincronizadas las unidades live dentro de `juli_tracker` (equipos + GeoJSON)."""
    if LIVE_TEAM_ID not in juli_tracker.teams:
        zone_lbl = next(iter(units.values())).zone_id if units else "Perímetro Incendio"
        juli_tracker.upsert_team(
            team_id=LIVE_TEAM_ID,
            name="Unidad First Response Live (Perímetro Incendio)",
            code="FR-LIVE",
            sector=zone_lbl,
            color="#EF4444",
            radio_channel="CH-01-TAC",
        )
    for u in units.values():
        op = juli_tracker.operators.get(u.id)
        if op is None:
            juli_tracker.upsert_operator(
                operator_id=u.id,
                name=f"{u.role.capitalize()} ({u.id})",
                team_id=LIVE_TEAM_ID,
                lon=round(u.lon, 6),
                lat=round(u.lat, 6),
                role=_ROLE_TO_TRACKER_ROLE.get(u.role, "brigadista"),
                status=_STATUS_TO_TRACKER_STATUS.get(u.status, "active"),
                callsign=u.id.upper(),
                battery_pct=u.battery,
                heart_rate_bpm=u.heart_rate if u.heart_rate > 0 else None,
                assigned_task=f"Despliegue en {u.zone_id}",
            )
        else:
            op.lon = round(u.lon, 6)
            op.lat = round(u.lat, 6)
            op.status = _STATUS_TO_TRACKER_STATUS.get(u.status, "active")
            op.battery_pct = u.battery
            op.heart_rate_bpm = u.heart_rate if u.heart_rate > 0 else None
            op.updated_at = datetime.now(timezone.utc).isoformat()
    if persist:
        juli_tracker.save()
        juli_tracker.export_geojson()


def _init_units_on_fire_zone() -> dict[str, RescueUnit]:
    zone_id, anchors = _load_fire_deployment_anchors()
    (b_lat, b_lon), (p_lat, p_lon), (d_lat, d_lon) = anchors
    units = {
        "unit-bombero-01": RescueUnit(
            id="unit-bombero-01",
            role="bombero",
            lat=b_lat,
            lon=b_lon,
            status="en_camino",
            battery=95,
            heart_rate=118,
            zone_id=zone_id,
            anchor_lat=b_lat,
            anchor_lon=b_lon,
            heading_deg=45.0,
        ),
        "unit-paramedico-02": RescueUnit(
            id="unit-paramedico-02",
            role="paramédico",
            lat=p_lat,
            lon=p_lon,
            status="activo",
            battery=88,
            heart_rate=89,
            zone_id=zone_id,
            anchor_lat=p_lat,
            anchor_lon=p_lon,
            heading_deg=135.0,
        ),
        "unit-dron-03": RescueUnit(
            id="unit-dron-03",
            role="dron",
            lat=d_lat,
            lon=d_lon,
            status="activo",
            battery=82,
            heart_rate=0,
            zone_id=zone_id,
            anchor_lat=d_lat,
            anchor_lon=d_lon,
            heading_deg=250.0,
        ),
    }
    _sync_units_to_tracker(units, persist=True)
    return units


UNITS: dict[str, RescueUnit] = _init_units_on_fire_zone()


# ---------------------------------------------------------------------------
# Utilidades de serialización (GeoJSON + array limpio) y simulación GPS
# ---------------------------------------------------------------------------


def _serialize_unit(unit: RescueUnit) -> dict:
    """Devuelve el diccionario limpio con los campos contractuales requeridos."""
    return {
        "id": unit.id,
        "role": unit.role,
        "lat": round(unit.lat, 6),
        "lon": round(unit.lon, 6),
        "status": unit.status,
        "battery": unit.battery,
        "heart_rate": unit.heart_rate,
    }


def build_units_payload() -> dict:
    """Construye un payload GeoJSON `FeatureCollection` con el array `units` incluido."""
    units_list = [_serialize_unit(u) for u in UNITS.values()]
    features = [
        {
            "type": "Feature",
            "id": u["id"],
            "geometry": {
                "type": "Point",
                "coordinates": [u["lon"], u["lat"]],
            },
            "properties": {
                **u,
                "zone_id": UNITS[u["id"]].zone_id,
                "team_id": LIVE_TEAM_ID,
                "marker_color": STATUS_COLORS.get(u["status"], "#3B82F6"),
            },
        }
        for u in units_list
    ]
    return {
        "type": "FeatureCollection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "units": units_list,
        "features": features,
    }


def step_simulation(tick_count: int) -> None:
    """Avanza un paso (2 s) manteniendo a las unidades en el perímetro del incendio."""
    max_patrol_radius_deg = 0.009  # ~1 km alrededor de su sector asignado
    for unit in UNITS.values():
        if unit.status != "sos":
            speed_deg = 0.00032 if unit.role == "dron" else 0.00018
            d_lat = unit.anchor_lat - unit.lat
            d_lon = unit.anchor_lon - unit.lon
            if math.hypot(d_lat, d_lon) > max_patrol_radius_deg:
                target_heading = math.degrees(math.atan2(d_lon, d_lat)) % 360.0
                unit.heading_deg = target_heading + random.uniform(-12.0, 12.0)
            else:
                unit.heading_deg = (unit.heading_deg + random.uniform(-20.0, 20.0)) % 360.0

            rad = math.radians(unit.heading_deg)
            unit.lat += math.cos(rad) * speed_deg
            unit.lon += math.sin(rad) * speed_deg

        if unit.role == "dron":
            unit.heart_rate = 0
        elif unit.status == "sos":
            unit.heart_rate = min(175, max(128, unit.heart_rate + random.randint(-2, 4)))
        else:
            unit.heart_rate = min(148, max(72, unit.heart_rate + random.randint(-3, 3)))

        if tick_count % 3 == 0 and unit.battery > 5:
            unit.battery -= 1

    _sync_units_to_tracker(UNITS, persist=False)


# ---------------------------------------------------------------------------
# Endpoints REST y WebSocket (en `juli_live_router`)
# ---------------------------------------------------------------------------


@juli_live_router.get("/api/units")
async def get_units() -> dict:
    """Devuelve el estado actual de todas las unidades para la carga inicial del mapa."""
    return build_units_payload()


@juli_live_router.post("/api/units/sync-fire")
async def resync_units_to_fire() -> dict:
    """Recoloca las unidades sobre la zona de incendio actual de `cata_predictions.json`."""
    global UNITS
    UNITS = _init_units_on_fire_zone()
    return {"status": "ok", "data": build_units_payload()}


@juli_live_router.post("/api/units/{unit_id}/sos")
async def trigger_unit_sos(unit_id: str) -> dict:
    """Fuerza el estado 'sos' de una unidad en vivo durante la demo."""
    unit = UNITS.get(unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"Unidad '{unit_id}' no encontrada.")
    unit.status = "sos"
    if unit.role != "dron":
        unit.heart_rate = max(unit.heart_rate, 140)
    _sync_units_to_tracker(UNITS, persist=True)
    return {
        "status": "ok",
        "alert": f"SOS activado para {unit_id}",
        "unit": _serialize_unit(unit),
        "data": build_units_payload(),
    }


@juli_live_router.websocket("/ws/tracking")
async def websocket_tracking(websocket: WebSocket) -> None:
    """Emite actualizaciones GPS y biométricas en tiempo real cada 2 segundos."""
    await websocket.accept()
    tick = 0
    try:
        await websocket.send_json(build_units_payload())
        while True:
            await asyncio.sleep(2.0)
            tick += 1
            step_simulation(tick)
            await websocket.send_json(build_units_payload())
    except WebSocketDisconnect:
        return


app.include_router(juli_live_router)


# En modo standalone también exponemos el GeoJSON/equipos de `juli_tracker`
@app.get("/api/juli/geojson")
async def get_juli_geojson_standalone(team_id: str | None = None) -> dict:
    """Devuelve el GeoJSON completo de equipos + unidades live de JULI."""
    return juli_tracker.build_geojson(team_filter=team_id)


@app.get("/api/juli/teams")
async def get_juli_teams_standalone() -> dict:
    """Devuelve todos los equipos y miembros registrados en JULI."""
    return {
        "algorithm": juli_config.ALGORITHM_NAME,
        "teams": juli_tracker.list_teams_with_members(),
    }
