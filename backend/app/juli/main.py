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
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

try:
    from . import config as juli_config
    from .chat import broadcast_proof_of_life_alerts_to_chat, chat_ws_manager, juli_chat
    from .chat_crypto import _b64_decode_flexible, build_crypto_spec
    from .coords import lonlat_to_quadrant_subcoords
    from .tracker import juli_tracker
    from .walkie_radio import build_protocol_spec as build_radio_protocol_spec, walkie_radio
except ImportError:  # Ejecución standalone desde backend/app/juli/
    import config as juli_config
    from chat import broadcast_proof_of_life_alerts_to_chat, chat_ws_manager, juli_chat
    from chat_crypto import _b64_decode_flexible, build_crypto_spec
    from coords import lonlat_to_quadrant_subcoords
    from tracker import juli_tracker
    from walkie_radio import build_protocol_spec as build_radio_protocol_spec, walkie_radio

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
    "dron": "piloto_dron",
}
_STATUS_TO_TRACKER_STATUS = {
    "activo": "en_terreno",
    "en_camino": "en_ruta",
    "sos": "alerta",
}


class ProofOfLifeConfirmInput(BaseModel):
    """Confirmación manual de prueba de vida de un operario."""

    lon: float | None = None
    lat: float | None = None
    elevation_m: float | None = None
    status: str | None = None
    battery_pct: int | None = Field(default=None, ge=0, le=100)
    heart_rate_bpm: int | None = Field(default=None, ge=25, le=240)
    note: str = ""


class ChatIdentityKeyInput(BaseModel):
    """Registro de clave pública ECDH P-256 (+ firma opcional ECDSA) para E2EE."""

    participant_id: str = Field(..., description="'central' o ID del operario (ej. 'op_hu_01')")
    ecdh_public_jwk: dict[str, Any] = Field(
        ..., description="Clave pública JWK P-256 (sin componente privado 'd')"
    )
    signing_public_jwk: dict[str, Any] | None = Field(
        default=None, description="Clave pública ECDSA P-256 opcional para firma de mensajes"
    )
    device_label: str = Field(default="", description="Etiqueta del dispositivo/navegador")
    display_name: str | None = Field(default=None, description="Nombre visible opcional")


class ChatDirectChannelInput(BaseModel):
    """Solicitud para abrir/recuperar un canal directo 1 a 1."""

    participant_a: str
    participant_b: str


class ChatIncidentChannelInput(BaseModel):
    """Creación de un canal táctico multi-escuadrón personalizado."""

    channel_id: str
    title: str
    member_ids: list[str]
    created_by: str = juli_config.CHAT_CENTRAL_ID


class ChatChannelKeysInput(BaseModel):
    """Claves de sala AES-256 envueltas por miembro para chats grupales E2EE."""

    sender_id: str
    wrapped_keys: dict[str, dict[str, Any]]
    key_epoch: int | None = Field(default=None, ge=1)
    sender_key_fingerprint: str = ""
    rotate_epoch: bool = False


class ChatAttachmentUploadInput(BaseModel):
    """Subida de imagen o PDF verificada antes de compartir en chat."""

    sender_id: str
    filename: str
    content_b64: str = Field(..., description="Contenido binario en base64 (máx. 10 MiB)")
    channel_id: str = Field(default=juli_config.CHAT_GLOBAL_CHANNEL_ID)
    declared_mime_type: str | None = None


class ChatSendMessageInput(BaseModel):
    """Sobre cifrado E2EE enviado a un canal de JULI (cero texto plano)."""

    channel_id: str = Field(
        default=juli_config.CHAT_GLOBAL_CHANNEL_ID,
        description="Canal destino; por defecto el chat general ('global:operativo')",
    )
    sender_id: str
    encryption: dict[str, Any]
    message_type: str = Field(default="text")
    client_msg_id: str | None = None
    reply_to_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)


class ChatAckInput(BaseModel):
    """Acuse de entrega o lectura de mensajes."""

    channel_id: str = Field(default=juli_config.CHAT_GLOBAL_CHANNEL_ID)
    participant_id: str
    message_ids: list[str]
    status: Literal["delivered", "read"] = "read"


class RadioSwitchInput(BaseModel):
    """Cambio de frecuencia / escuadrón desde walkie-talkie moderno (BLE GATT + TETRA PEI)."""

    operator_id: str
    target_team_id: str | None = None
    target_frequency_mhz: float | None = Field(default=None, gt=0.0)
    target_radio_channel: str | None = None
    target_talkgroup_id: str | None = None
    at_command: str | None = Field(
        default=None, description="Ej. 'AT+CTGS=2002' o 'AT+CFREQ=154.625'"
    )
    ble_payload_hex: str | None = Field(
        default=None, description="Carga hexadecimal recibida en la característica RX BLE GATT"
    )
    ble_device_id: str = ""
    simulated: bool = False
    note: str = ""


class RadioPeiCommandInput(BaseModel):
    """Comando crudo TETRA PEI AT enviado desde terminal móvil / BLE bridge."""

    operator_id: str
    command: str | None = None
    ble_payload_hex: str | None = None
    ble_device_id: str = ""
    simulated: bool = False


class RescueUnit(BaseModel):
    """Representa una unidad de emergencias desplegada en el perímetro del incendio."""

    id: str
    role: UnitRole
    lat: float
    lon: float
    status: UnitStatus
    battery: int
    heart_rate: int
    team_id: str = LIVE_TEAM_ID
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
            unit_code="FR-LIVE",
            vehicle_type="Autobomba + Sanitario + Dron Térmico",
            radio_channel="VHF-TAC",
            zone_assigned=zone_lbl,
            color="#EF4444",
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
                status=_STATUS_TO_TRACKER_STATUS.get(u.status, "en_terreno"),
                callsign=u.id.upper(),
                battery_pct=u.battery,
                heart_rate_bpm=u.heart_rate if u.heart_rate > 0 else None,
            )
        else:
            u.team_id = op.team_id
            juli_tracker.sync_unit_position(
                operator_id=u.id,
                lon=u.lon,
                lat=u.lat,
                status=_STATUS_TO_TRACKER_STATUS.get(u.status, "en_terreno"),
                battery_pct=u.battery,
                heart_rate_bpm=u.heart_rate if u.heart_rate > 0 else None,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
    if persist:
        juli_tracker.save_state()
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
    """Devuelve posición absoluta WGS84/EPSG:3035 + cuadrante 1000x1000m + subcoordenadas."""
    loc = lonlat_to_quadrant_subcoords(unit.lon, unit.lat)
    tracked = juli_tracker.operators.get(unit.id)
    effective_team = tracked.team_id if tracked else unit.team_id
    return {
        "id": unit.id,
        "role": unit.role,
        "team_id": effective_team,
        "radio_channel": tracked.radio_channel if tracked else "VHF-TAC",
        "radio_frequency_mhz": tracked.radio_frequency_mhz if tracked else None,
        "talkgroup_id": tracked.talkgroup_id if tracked else "3003",
        "lat": loc["lat"],
        "lon": loc["lon"],
        "status": unit.status,
        "battery": unit.battery,
        "heart_rate": unit.heart_rate,
        **loc,
        "quadrant_location": loc,
    }


def build_units_payload() -> dict:
    """Construye un payload GeoJSON `FeatureCollection` con el array `units` incluido."""
    pol_eval = juli_tracker.evaluate_proof_of_life()
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
                "marker_color": STATUS_COLORS.get(u["status"], "#3B82F6"),
            },
        }
        for u in units_list
    ]
    return {
        "type": "FeatureCollection",
        "quadrant_grid": {
            "crs": juli_config.GRID_CRS,
            "cell_prefix": juli_config.CELL_PREFIX,
            "grid_level": juli_config.GRID_LEVEL,
            "cell_size_m": juli_config.CELL_SIZE_M,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "units": units_list,
        "proof_of_life": {
            "checked_at": pol_eval["checked_at"],
            "immobile_threshold_seconds": pol_eval["immobile_threshold_seconds"],
            "active_alerts_count": pol_eval["active_alerts_count"],
            "alerts": pol_eval["alerts"],
        },
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


@juli_live_router.get("/api/juli/proof-of-life")
async def get_juli_proof_of_life(
    immobile_seconds: int = Query(
        default=juli_config.PROOF_OF_LIFE_IMMOBILE_SECONDS,
        ge=1,
    ),
) -> dict:
    """Evalúa la prueba de vida (>= 15 min inmóvil o cuadrante en llamas) para Central y escuadrones."""
    return {
        "algorithm": juli_config.ALGORITHM_NAME,
        **juli_tracker.evaluate_proof_of_life(immobile_seconds=immobile_seconds),
    }


@juli_live_router.post("/api/juli/operators/{operator_id}/proof-of-life")
async def confirm_juli_operator_proof_of_life(
    operator_id: str,
    req: ProofOfLifeConfirmInput | None = None,
) -> dict:
    """Confirma manualmente la prueba de vida de un operario y reinicia el contador."""
    body = req or ProofOfLifeConfirmInput()
    try:
        confirmed = juli_tracker.confirm_proof_of_life(
            operator_id=operator_id,
            lon=body.lon,
            lat=body.lat,
            elevation_m=body.elevation_m,
            status=body.status,
            battery_pct=body.battery_pct,
            heart_rate_bpm=body.heart_rate_bpm,
            note=body.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    pol_events = juli_tracker.poll_proof_of_life_events()
    return {
        "status": "ok",
        **confirmed,
        "proof_of_life_events": pol_events["events"],
        "geojson": juli_tracker.build_geojson(),
    }


@juli_live_router.websocket("/ws/tracking")
async def websocket_tracking(websocket: WebSocket) -> None:
    """Emite actualizaciones GPS, biométricas y alertas de prueba de vida en tiempo real."""
    await websocket.accept()
    tick = 0
    try:
        await websocket.send_json(build_units_payload())
        initial_pol = juli_tracker.evaluate_proof_of_life()
        for alert in initial_pol["alerts"]:
            await websocket.send_json(alert)
        while True:
            await asyncio.sleep(2.0)
            tick += 1
            step_simulation(tick)
            pol_events = juli_tracker.poll_proof_of_life_events()
            await websocket.send_json(build_units_payload())
            for event in pol_events["events"]:
                await websocket.send_json(event)
            await broadcast_proof_of_life_alerts_to_chat(pol_events["events"])
    except WebSocketDisconnect:
        return


# ---------------------------------------------------------------------------
# Endpoints REST y WebSocket de Chat E2EE (`juli_live_router`)
# ---------------------------------------------------------------------------


def _chat_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@juli_live_router.get("/api/juli/chat/crypto-spec")
async def get_juli_chat_crypto_spec() -> dict:
    """Devuelve los parámetros WebCrypto E2EE para configurar el cliente de chat."""
    return build_crypto_spec()


@juli_live_router.post("/api/juli/chat/keys")
async def register_juli_chat_key(req: ChatIdentityKeyInput) -> dict:
    """Registra o rota la clave pública ECDH P-256 de un operario o de Central."""
    try:
        rec = juli_chat.register_identity_key(
            participant_id=req.participant_id,
            ecdh_public_jwk=req.ecdh_public_jwk,
            signing_public_jwk=req.signing_public_jwk,
            device_label=req.device_label,
            display_name=req.display_name,
        )
    except (KeyError, ValueError) as exc:
        raise _chat_http_error(exc) from exc

    await chat_ws_manager.broadcast_to_participants(
        chat_ws_manager.online_participants(),
        {
            "event": "chat_key_updated",
            "participant_id": rec["participant_id"],
            "fingerprint": rec["fingerprint"],
            "short_fingerprint": rec["short_fingerprint"],
            "key_version": rec["key_version"],
        },
        exclude_participant=rec["participant_id"],
    )
    return {"status": "ok", "identity_key": rec}


@juli_live_router.get("/api/juli/chat/keys")
async def list_juli_chat_keys(
    team_id: str | None = Query(default=None),
    viewer_id: str | None = Query(default=None),
) -> dict:
    """Lista claves públicas E2EE y códigos de seguridad relativos a `viewer_id`."""
    return {
        "protocol": "JULI-E2EE-v1",
        "keys": juli_chat.list_identity_keys(team_id=team_id, viewer_id=viewer_id),
    }


@juli_live_router.get("/api/juli/chat/keys/{participant_id}")
async def get_juli_chat_key(
    participant_id: str,
    viewer_id: str | None = Query(default=None),
) -> dict:
    """Obtiene la clave pública de un participante concreto."""
    keys = juli_chat.list_identity_keys(viewer_id=viewer_id)
    match = next((k for k in keys if k["participant_id"] == participant_id.strip()), None)
    if match is None:
        raise HTTPException(
            status_code=404,
            detail=f"El participante '{participant_id}' aún no ha publicado su clave pública.",
        )
    return {"status": "ok", "identity_key": match}


@juli_live_router.delete("/api/juli/chat/keys/{participant_id}")
async def revoke_juli_chat_key(participant_id: str) -> dict:
    """Revoca la clave pública de un dispositivo comprometido o dado de baja."""
    try:
        rec = juli_chat.revoke_identity_key(participant_id)
    except KeyError as exc:
        raise _chat_http_error(exc) from exc

    await chat_ws_manager.broadcast_to_participants(
        chat_ws_manager.online_participants(),
        {
            "event": "chat_key_revoked",
            "participant_id": rec["participant_id"],
            "fingerprint": rec["fingerprint"],
        },
    )
    return {"status": "ok", "identity_key": rec}


@juli_live_router.get("/api/juli/chat/safety-code")
async def get_juli_chat_safety_code(
    participant_a: str = Query(...),
    participant_b: str = Query(...),
) -> dict:
    """Calcula el código numérico simétrico de verificación entre dos identidades."""
    try:
        return juli_chat.get_safety_code(participant_a, participant_b)
    except KeyError as exc:
        raise _chat_http_error(exc) from exc


@juli_live_router.get("/api/juli/chat/channels")
async def list_juli_chat_channels(
    participant_id: str | None = Query(default=None),
) -> dict:
    """Lista canales de chat disponibles (escuadrón, directo, incidente, global)."""
    return {
        "protocol": "JULI-E2EE-v1",
        "default_channel_id": juli_config.CHAT_GLOBAL_CHANNEL_ID,
        "online_participants": chat_ws_manager.online_participants(),
        "channels": juli_chat.list_channels(participant_id=participant_id),
    }


@juli_live_router.post("/api/juli/chat/channels/direct")
async def open_juli_direct_channel(req: ChatDirectChannelInput) -> dict:
    """Abre o recupera el canal E2EE 1 a 1 entre dos participantes."""
    try:
        channel = juli_chat.open_direct_channel(req.participant_a, req.participant_b)
    except (KeyError, ValueError) as exc:
        raise _chat_http_error(exc) from exc
    return {"status": "ok", "channel": channel}


@juli_live_router.post("/api/juli/chat/channels")
async def create_juli_incident_channel(req: ChatIncidentChannelInput) -> dict:
    """Crea una sala táctica personalizada multi-escuadrón."""
    try:
        channel = juli_chat.create_incident_channel(
            channel_id=req.channel_id,
            title=req.title,
            member_ids=req.member_ids,
            created_by=req.created_by,
        )
    except (KeyError, ValueError) as exc:
        raise _chat_http_error(exc) from exc
    return {"status": "ok", "channel": channel}


@juli_live_router.post("/api/juli/chat/channels/{channel_id}/keys")
async def publish_juli_channel_keys(channel_id: str, req: ChatChannelKeysInput) -> dict:
    """Publica las claves de sala AES-256 envueltas por miembro para cifrado de grupo E2EE."""
    try:
        result = juli_chat.publish_channel_keys(
            channel_id=channel_id,
            sender_id=req.sender_id,
            wrapped_keys=req.wrapped_keys,
            key_epoch=req.key_epoch,
            sender_key_fingerprint=req.sender_key_fingerprint,
            rotate_epoch=req.rotate_epoch,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _chat_http_error(exc) from exc

    await chat_ws_manager.broadcast_to_participants(
        result["recipients"],
        {
            "event": "chat_key_bundle",
            **result,
        },
        exclude_participant=req.sender_id,
    )
    return {"status": "ok", **result}


@juli_live_router.get("/api/juli/chat/channels/{channel_id}/keys")
async def get_juli_channel_key(
    channel_id: str,
    participant_id: str = Query(...),
    key_epoch: int | None = Query(default=None, ge=1),
) -> dict:
    """Obtiene el sobre de clave de sala cifrado exclusivamente para `participant_id`."""
    try:
        key_pkg = juli_chat.get_channel_key_for_participant(
            channel_id=channel_id,
            participant_id=participant_id,
            key_epoch=key_epoch,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _chat_http_error(exc) from exc
    return {"status": "ok", **key_pkg}


@juli_live_router.post("/api/juli/chat/attachments")
async def upload_juli_chat_attachment(req: ChatAttachmentUploadInput) -> dict:
    """Inspecciona (magic bytes, estructura, CDR/antimalware) y guarda imagen o PDF."""
    try:
        raw_bytes = _b64_decode_flexible(req.content_b64, field_name="content_b64")
        att = juli_chat.upload_attachment(
            sender_id=req.sender_id,
            filename=req.filename,
            content_bytes=raw_bytes,
            channel_id=req.channel_id,
            declared_mime_type=req.declared_mime_type,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _chat_http_error(exc) from exc
    return {"status": "ok", "attachment": att}


@juli_live_router.get("/api/juli/chat/attachments/{attachment_id}")
async def download_juli_chat_attachment(
    attachment_id: str,
    participant_id: str = Query(...),
) -> Response:
    """Sirve una imagen o PDF ya verificado con cabeceras seguras (`nosniff` + CSP sandbox)."""
    try:
        att, raw_bytes = juli_chat.get_attachment_content(attachment_id, participant_id)
    except (KeyError, PermissionError, ValueError) as exc:
        raise _chat_http_error(exc) from exc

    return Response(
        content=raw_bytes,
        media_type=att["mime_type"],
        headers={
            "Content-Disposition": f'inline; filename="{att["safe_filename"]}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-SHA256": att["sha256"],
            "Cache-Control": "private, max-age=3600",
        },
    )


@juli_live_router.post("/api/juli/chat/messages")
async def send_juli_chat_message(req: ChatSendMessageInput) -> dict:
    """Envía un mensaje E2EE al canal y lo difunde en tiempo real vía WebSocket."""
    try:
        msg, created = juli_chat.send_message(
            channel_id=req.channel_id,
            sender_id=req.sender_id,
            encryption=req.encryption,
            message_type=req.message_type,
            client_msg_id=req.client_msg_id,
            reply_to_id=req.reply_to_id,
            attachment_ids=req.attachment_ids,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _chat_http_error(exc) from exc

    if created:
        await chat_ws_manager.broadcast_to_participants(
            msg["recipients"],
            {
                "event": "chat_message",
                "channel_id": msg["channel_id"],
                "message": msg,
            },
            exclude_participant=req.sender_id,
        )
    return {"status": "ok", "created": created, "message": msg}


@juli_live_router.get("/api/juli/chat/messages")
async def list_juli_chat_messages(
    channel_id: str = Query(default=juli_config.CHAT_GLOBAL_CHANNEL_ID),
    participant_id: str = Query(...),
    since_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """Recupera el historial cifrado E2EE de un canal para un miembro autorizado."""
    try:
        return juli_chat.list_messages(
            channel_id=channel_id,
            participant_id=participant_id,
            since_seq=since_seq,
            limit=limit,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _chat_http_error(exc) from exc


@juli_live_router.post("/api/juli/chat/messages/ack")
async def ack_juli_chat_messages(req: ChatAckInput) -> dict:
    """Confirma entrega o lectura de mensajes sin revelar contenido y notifica al canal."""
    try:
        receipt = juli_chat.ack_messages(
            channel_id=req.channel_id,
            participant_id=req.participant_id,
            message_ids=req.message_ids,
            status=req.status,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _chat_http_error(exc) from exc

    if receipt["message_ids"]:
        await chat_ws_manager.broadcast_to_participants(
            receipt["recipients"],
            receipt,
            exclude_participant=req.participant_id,
        )
    return {"status": "ok", **receipt}


@juli_live_router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    participant_id: str = Query(..., description="'central' o ID del operario"),
) -> None:
    """Canal WebSocket en tiempo real para mensajería E2EE, intercambio de claves y presencia."""
    pid = participant_id.strip()
    if juli_chat._resolve_participant(pid) is None:
        await websocket.close(code=1008, reason=f"Participante '{pid}' no registrado en JULI.")
        return

    await chat_ws_manager.connect(pid, websocket)
    try:
        await websocket.send_json(
            {
                "event": "chat_welcome",
                "participant_id": pid,
                "default_channel_id": juli_config.CHAT_GLOBAL_CHANNEL_ID,
                "crypto_spec": build_crypto_spec(),
                "has_registered_key": pid in juli_chat.identity_keys
                and not juli_chat.identity_keys[pid].revoked,
                "online_participants": chat_ws_manager.online_participants(),
                "channels": juli_chat.list_channels(participant_id=pid),
            }
        )
        await chat_ws_manager.broadcast_to_participants(
            chat_ws_manager.online_participants(),
            {
                "event": "chat_presence",
                "participant_id": pid,
                "online": True,
                "online_participants": chat_ws_manager.online_participants(),
            },
            exclude_participant=pid,
        )

        while True:
            frame = await websocket.receive_json()
            action = str(frame.get("action", "")).strip()

            try:
                if action == "ping":
                    await websocket.send_json({"event": "pong"})

                elif action == "send_message":
                    msg, created = juli_chat.send_message(
                        channel_id=frame.get("channel_id") or juli_config.CHAT_GLOBAL_CHANNEL_ID,
                        sender_id=pid,
                        encryption=frame["encryption"],
                        message_type=frame.get("message_type", "text"),
                        client_msg_id=frame.get("client_msg_id"),
                        reply_to_id=frame.get("reply_to_id"),
                        attachment_ids=frame.get("attachment_ids"),
                    )
                    await websocket.send_json(
                        {
                            "event": "chat_message_ack",
                            "created": created,
                            "message": msg,
                        }
                    )
                    if created:
                        await chat_ws_manager.broadcast_to_participants(
                            msg["recipients"],
                            {
                                "event": "chat_message",
                                "channel_id": msg["channel_id"],
                                "message": msg,
                            },
                            exclude_participant=pid,
                        )

                elif action == "publish_keys":
                    res = juli_chat.publish_channel_keys(
                        channel_id=frame.get("channel_id") or juli_config.CHAT_GLOBAL_CHANNEL_ID,
                        sender_id=pid,
                        wrapped_keys=frame["wrapped_keys"],
                        key_epoch=frame.get("key_epoch"),
                        sender_key_fingerprint=frame.get("sender_key_fingerprint", ""),
                        rotate_epoch=bool(frame.get("rotate_epoch", False)),
                    )
                    await websocket.send_json({"event": "chat_keys_published", **res})
                    await chat_ws_manager.broadcast_to_participants(
                        res["recipients"],
                        {"event": "chat_key_bundle", **res},
                        exclude_participant=pid,
                    )

                elif action == "ack":
                    receipt = juli_chat.ack_messages(
                        channel_id=frame.get("channel_id") or juli_config.CHAT_GLOBAL_CHANNEL_ID,
                        participant_id=pid,
                        message_ids=frame.get("message_ids", []),
                        status=frame.get("status", "read"),
                    )
                    if receipt["message_ids"]:
                        await chat_ws_manager.broadcast_to_participants(
                            receipt["recipients"],
                            receipt,
                            exclude_participant=pid,
                        )

                elif action == "typing":
                    ch = juli_chat._get_or_auto_channel(
                        frame.get("channel_id") or juli_config.CHAT_GLOBAL_CHANNEL_ID
                    )
                    if not juli_chat.has_channel_access(pid, ch):
                        raise PermissionError(f"'{pid}' no pertenece a '{ch.channel_id}'.")
                    await chat_ws_manager.broadcast_to_participants(
                        juli_chat.channel_recipients(ch),
                        {
                            "event": "chat_typing",
                            "channel_id": ch.channel_id,
                            "participant_id": pid,
                            "is_typing": bool(frame.get("is_typing", True)),
                        },
                        exclude_participant=pid,
                    )

                else:
                    raise ValueError(f"Acción WebSocket no soportada: '{action}'.")
            except (KeyError, PermissionError, TypeError, ValueError) as exc:
                await websocket.send_json(
                    {
                        "event": "chat_error",
                        "action": action,
                        "detail": str(exc),
                    }
                )
    except WebSocketDisconnect:
        chat_ws_manager.disconnect(pid, websocket)
        await chat_ws_manager.broadcast_to_participants(
            chat_ws_manager.online_participants(),
            {
                "event": "chat_presence",
                "participant_id": pid,
                "online": False,
                "online_participants": chat_ws_manager.online_participants(),
            },
        )


_RADIO_WS_SUBSCRIBERS: dict[str, list[WebSocket]] = {}
_EXTERNAL_RADIO_EVENT_HOOKS: list[Any] = []


def register_radio_event_hook(callback: Any) -> None:
    """Permite a `app.main` recibir eventos de cambio de frecuencia para reemitirlos en `/ws`."""
    if callback not in _EXTERNAL_RADIO_EVENT_HOOKS:
        _EXTERNAL_RADIO_EVENT_HOOKS.append(callback)


async def _after_radio_switch(record: dict[str, Any]) -> dict[str, Any]:
    """Sincroniza unidades live, chat, GeoJSON y difunde el cambio a Central y escuadrones."""
    oid = record["operator_id"]
    new_tid = record["current"]["team_id"]
    if oid in UNITS:
        UNITS[oid].team_id = new_tid

    # Actualiza membresía de canales de chat y obtiene GeoJSON y equipos actualizados
    juli_chat._sync_default_channels()
    geojson_payload = juli_tracker.build_geojson()
    teams_payload = juli_tracker.list_teams_with_members()

    prev_tid = record["previous"]["team_id"]
    notify_targets = sorted(
        {
            juli_config.CHAT_CENTRAL_ID,
            oid,
            *[
                op.operator_id
                for op in juli_tracker.operators.values()
                if op.team_id in (prev_tid, new_tid)
            ],
        }
    )
    ws_event = {
        **record,
        "geojson": geojson_payload,
    }
    await chat_ws_manager.broadcast_to_participants(notify_targets, ws_event)

    for target_id in (oid, "*"):
        for ws in list(_RADIO_WS_SUBSCRIBERS.get(target_id, ())):
            try:
                await ws.send_json(ws_event)
            except Exception:
                _RADIO_WS_SUBSCRIBERS[target_id].remove(ws)

    for hook in list(_EXTERNAL_RADIO_EVENT_HOOKS):
        try:
            await hook(ws_event)
        except Exception:
            pass

    return {
        **record,
        "geojson": geojson_payload,
        "teams": teams_payload,
    }


@juli_live_router.get("/api/juli/radio/protocol")
async def get_juli_radio_protocol() -> dict:
    """Especificación BLE GATT + TETRA PEI AT para enlace walkie-talkie <-> terminal móvil."""
    return build_radio_protocol_spec()


@juli_live_router.get("/api/juli/radio/frequencies")
async def get_juli_radio_frequencies() -> dict:
    """Devuelve el plan de frecuencias/talkgroups (VHF/TETRA/GSSI) de todos los escuadrones."""
    return {
        "protocol": juli_config.RADIO_DEFAULT_PROTOCOL,
        "frequencies": walkie_radio.get_frequency_bank(),
    }


@juli_live_router.get("/api/juli/radio/operators/{operator_id}")
async def get_juli_operator_radio(operator_id: str) -> dict:
    """Estado RF/BLE y frecuencia actual sintonizada por un operario."""
    try:
        return {"status": "ok", "radio": walkie_radio.get_operator_radio_state(operator_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@juli_live_router.get("/api/juli/radio/history")
async def get_juli_radio_history(
    limit: int = Query(default=50, ge=1, le=200),
    operator_id: str | None = Query(default=None),
) -> dict:
    """Histórico reciente de cambios de frecuencia (reales y simulados)."""
    return {
        "protocol": juli_config.RADIO_DEFAULT_PROTOCOL,
        "history": walkie_radio.get_history(limit=limit, operator_id=operator_id),
    }


@juli_live_router.post("/api/juli/radio/switch")
async def switch_juli_radio_frequency(req: RadioSwitchInput) -> dict:
    """Cambia la frecuencia/talkgroup del operario y lo mueve automáticamente de escuadrón."""
    try:
        record = walkie_radio.switch_frequency(
            operator_id=req.operator_id,
            target_team_id=req.target_team_id,
            target_frequency_mhz=req.target_frequency_mhz,
            target_radio_channel=req.target_radio_channel,
            target_talkgroup_id=req.target_talkgroup_id,
            at_command=req.at_command,
            ble_payload_hex=req.ble_payload_hex,
            ble_device_id=req.ble_device_id,
            simulated=req.simulated,
            note=req.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _after_radio_switch(record)


@juli_live_router.post("/api/juli/radio/simulate-switch")
async def simulate_juli_radio_switch(req: RadioSwitchInput) -> dict:
    """Simula el cambio de frecuencia BLE GATT + TETRA PEI hacia otro escuadrón."""
    try:
        record = walkie_radio.switch_frequency(
            operator_id=req.operator_id,
            target_team_id=req.target_team_id,
            target_frequency_mhz=req.target_frequency_mhz,
            target_radio_channel=req.target_radio_channel,
            target_talkgroup_id=req.target_talkgroup_id,
            at_command=req.at_command,
            ble_payload_hex=req.ble_payload_hex,
            ble_device_id=req.ble_device_id,
            simulated=True,
            note=req.note or "Simulación de cambio de frecuencia walkie-talkie",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _after_radio_switch(record)


@juli_live_router.post("/api/juli/radio/pei")
async def execute_juli_radio_pei(req: RadioPeiCommandInput) -> dict:
    """Ejecuta un comando crudo AT TETRA PEI (consulta o cambio de talkgroup/frecuencia)."""
    try:
        result = walkie_radio.execute_pei_command(
            operator_id=req.operator_id,
            command=req.command,
            ble_payload_hex=req.ble_payload_hex,
            ble_device_id=req.ble_device_id,
            simulated=req.simulated,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result.get("event") == "juli_radio_frequency_switched":
        return await _after_radio_switch(result)
    return result


@juli_live_router.websocket("/ws/radio")
async def websocket_radio_bridge(
    websocket: WebSocket,
    operator_id: str = Query(
        default="*",
        description="ID del operario del terminal móvil o '*' para consola Central",
    ),
) -> None:
    """Puente WebSocket BLE GATT <-> TETRA PEI para terminales móviles y simuladores."""
    sub_key = operator_id.strip() or "*"
    if sub_key != "*" and sub_key not in juli_tracker.operators:
        await websocket.close(code=1008, reason=f"Operario '{sub_key}' no registrado en JULI.")
        return

    await websocket.accept()
    _RADIO_WS_SUBSCRIBERS.setdefault(sub_key, []).append(websocket)
    try:
        welcome: dict[str, Any] = {
            "event": "radio_bridge_welcome",
            "protocol_spec": build_radio_protocol_spec(),
            "frequencies": walkie_radio.get_frequency_bank(),
        }
        if sub_key != "*":
            welcome["radio_state"] = walkie_radio.get_operator_radio_state(sub_key)
        await websocket.send_json(welcome)

        while True:
            frame = await websocket.receive_json()
            action = str(frame.get("action", "")).strip()
            target_oid = str(frame.get("operator_id") or ("" if sub_key == "*" else sub_key)).strip()
            try:
                if action == "ping":
                    await websocket.send_json({"event": "pong"})
                elif action == "pei":
                    res = walkie_radio.execute_pei_command(
                        operator_id=target_oid,
                        command=frame.get("command"),
                        ble_payload_hex=frame.get("ble_payload_hex"),
                        ble_device_id=frame.get("ble_device_id", ""),
                        simulated=bool(frame.get("simulated", False)),
                    )
                    if res.get("event") == "juli_radio_frequency_switched":
                        payload = await _after_radio_switch(res)
                        await websocket.send_json(payload)
                    else:
                        await websocket.send_json(res)
                elif action in ("switch", "simulate_switch"):
                    rec = walkie_radio.switch_frequency(
                        operator_id=target_oid,
                        target_team_id=frame.get("target_team_id"),
                        target_frequency_mhz=frame.get("target_frequency_mhz"),
                        target_radio_channel=frame.get("target_radio_channel"),
                        target_talkgroup_id=frame.get("target_talkgroup_id"),
                        at_command=frame.get("at_command"),
                        ble_payload_hex=frame.get("ble_payload_hex"),
                        ble_device_id=frame.get("ble_device_id", ""),
                        simulated=bool(frame.get("simulated", action == "simulate_switch")),
                        note=frame.get("note", ""),
                    )
                    await websocket.send_json(await _after_radio_switch(rec))
                else:
                    raise ValueError(f"Acción de radio no soportada: '{action}'.")
            except (KeyError, ValueError, TypeError) as exc:
                await websocket.send_json({"event": "radio_error", "detail": str(exc)})
    except WebSocketDisconnect:
        subs = _RADIO_WS_SUBSCRIBERS.get(sub_key, [])
        if websocket in subs:
            subs.remove(websocket)


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
