"""Gestor de equipos y operarios en terreno de JULI con exportación GeoJSON (WGS84 / RFC 7946).

JULI es un módulo independiente de la pipeline VALEN -> CATA -> LUCIA dedicado a llevar el
control actualizado de los equipos de intervención y de cada operario desplegado en el terreno,
devolviendo su posición y telemetría en formato GeoJSON listo para el Frontend (CesiumJS / deck.gl).
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import config
from .coords import lonlat_to_quadrant_subcoords, quadrant_subcoords_to_lonlat

_LOGGER = logging.getLogger("juli.tracker")


def _now_utc(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _now_iso(now: datetime | None = None) -> str:
    return _now_utc(now).isoformat()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        try:
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None
    return _now_utc(dt)


def _displacement_m(lon_a: float, lat_a: float, lon_b: float, lat_b: float) -> float:
    """Distancia euclídea real (m) en EPSG:3035 entre dos coordenadas WGS84."""
    loc_a = lonlat_to_quadrant_subcoords(lon_a, lat_a)
    loc_b = lonlat_to_quadrant_subcoords(lon_b, lat_b)
    return math.hypot(
        loc_b["epsg3035_x_m"] - loc_a["epsg3035_x_m"],
        loc_b["epsg3035_y_m"] - loc_a["epsg3035_y_m"],
    )


def load_burning_quadrants(
    cata_predictions_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Carga los cuadrantes 1000x1000m en llamas o riesgo inminente desde CATA."""
    target_path = cata_predictions_path or config.DEFAULT_CATA_PREDICTIONS_PATH
    if not target_path or not os.path.exists(target_path):
        return {}

    try:
        with open(target_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    burning: dict[str, dict[str, Any]] = {}
    for cell in data.get("active_and_predicted_cells") or []:
        qid = cell.get("cell_id") or cell.get("quadrant_id")
        if not qid:
            continue
        state = int(cell.get("quadrant_state", 0))
        if state in config.PROOF_OF_LIFE_BURNING_STATES:
            burning[str(qid)] = {
                "quadrant_id": str(qid),
                "quadrant_state": state,
                "state_label": cell.get("quadrant_label") or cell.get("state_label", ""),
                "zone_id": cell.get("zone_id", ""),
                "zone_name": cell.get("zone_name", ""),
                "fire_probability_t1": cell.get("fire_probability_t1"),
                "estimated_arrival_hours": cell.get("estimated_arrival_hours"),
            }
    return burning


@dataclass
class Operator:
    """Representa una persona (operario) integrada dentro de un equipo en el terreno."""

    operator_id: str
    name: str
    team_id: str
    lon: float
    lat: float
    elevation_m: float = 0.0
    role: str = "brigadista"
    status: str = "en_terreno"
    callsign: str = ""
    battery_pct: int = 100
    heart_rate_bpm: int | None = None
    updated_at: str = field(default_factory=_now_iso)
    last_moved_at: str = ""
    last_proof_of_life_at: str = ""
    radio_channel: str = ""
    radio_frequency_mhz: float | None = None
    talkgroup_id: str = ""
    radio_protocol: str = config.RADIO_DEFAULT_PROTOCOL
    radio_device_id: str = ""
    radio_last_switch_at: str = ""

    def __post_init__(self) -> None:
        if not self.last_moved_at:
            self.last_moved_at = self.updated_at
        if not self.last_proof_of_life_at:
            self.last_proof_of_life_at = self.last_moved_at

    def quadrant_location(self) -> dict[str, Any]:
        """Devuelve el cuadrante 1000x1000m, sus subcoordenadas y las coordenadas absolutas."""
        return lonlat_to_quadrant_subcoords(self.lon, self.lat)

    def last_location_payload(self, now: datetime | None = None) -> dict[str, Any]:
        """Última localización precisa priorizada para alertas de prueba de vida."""
        loc = self.quadrant_location()
        now_ref = _now_utc(now)
        moved_dt = _parse_iso(self.last_moved_at) or _parse_iso(self.updated_at) or now_ref
        immobile_seconds = max(0, int((now_ref - moved_dt).total_seconds()))
        return {
            "lon": self.lon,
            "lat": self.lat,
            "elevation_m": self.elevation_m,
            "quadrant_id": loc["quadrant_id"],
            "offset_x_m": loc["offset_x_m"],
            "offset_y_m": loc["offset_y_m"],
            "sub_cell_id": loc["sub_cell_id"],
            "sub_100m_rc": loc["sub_100m_rc"],
            "sub_10m_rc": loc["sub_10m_rc"],
            "epsg3035_x_m": loc["epsg3035_x_m"],
            "epsg3035_y_m": loc["epsg3035_y_m"],
            "recorded_at": self.updated_at,
            "last_moved_at": self.last_moved_at,
            "last_proof_of_life_at": self.last_proof_of_life_at,
            "immobile_seconds": immobile_seconds,
        }

    def to_dict(self) -> dict[str, Any]:
        loc = self.quadrant_location()
        return {
            **asdict(self),
            **loc,
            "quadrant_location": loc,
        }


@dataclass
class Team:
    """Representa un equipo / cuadrilla de operarios desplegado en una zona."""

    team_id: str
    name: str
    unit_code: str = "BRIF-A"
    vehicle_type: str = "Autobomba Pesada 4x4"
    radio_channel: str = "CH-04"
    zone_assigned: str = "Sector Sur"
    color: str = "#06b6d4"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _default_seed_data() -> tuple[dict[str, Team], dict[str, Operator]]:
    """Crea un conjunto inicial realista de equipos y operarios en el terreno."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    teams = {
        "team_brif_huelva": Team(
            team_id="team_brif_huelva",
            name="Cuadrilla BRIF Alfa — Doñana / Almonte",
            unit_code="BRIF-HU-01",
            vehicle_type="Autobomba Forestal 4x4 + Helitransporte",
            radio_channel="VHF-01",
            zone_assigned="ES1K_block_110_179",
            color=config.TEAM_PALETTE[0],
            created_at=now,
        ),
        "team_ume_zamora": Team(
            team_id="team_ume_zamora",
            name="Pelotón UME Bravo — Sierra de la Culebra",
            unit_code="UME-ZA-02",
            vehicle_type="Nodriza Pesada + Dron Térmico",
            radio_channel="VHF-02",
            zone_assigned="ES1K_block_131_201",
            color=config.TEAM_PALETTE[1],
            created_at=now,
        ),
    }

    operators = {
        "op_hu_01": Operator(
            operator_id="op_hu_01",
            name="Carlos Méndez",
            team_id="team_brif_huelva",
            lon=-6.4182,
            lat=37.6415,
            elevation_m=312.0,
            role="jefe_cuadrilla",
            status="en_terreno",
            callsign="ALFA-1",
            battery_pct=92,
            heart_rate_bpm=98,
            updated_at=now,
        ),
        "op_hu_02": Operator(
            operator_id="op_hu_02",
            name="Elena Vargas",
            team_id="team_brif_huelva",
            lon=-6.4148,
            lat=37.6438,
            elevation_m=318.5,
            role="brigadista",
            status="en_terreno",
            callsign="ALFA-2",
            battery_pct=87,
            heart_rate_bpm=112,
            updated_at=now,
        ),
        "op_hu_03": Operator(
            operator_id="op_hu_03",
            name="Javier Romero",
            team_id="team_brif_huelva",
            lon=-6.4110,
            lat=37.6392,
            elevation_m=305.0,
            role="conductor_autobomba",
            status="en_ruta",
            callsign="ALFA-3",
            battery_pct=96,
            heart_rate_bpm=84,
            updated_at=now,
        ),
        "op_hu_04": Operator(
            operator_id="op_hu_04",
            name="Sofía Martín",
            team_id="team_brif_huelva",
            lon=-6.4165,
            lat=37.6401,
            elevation_m=310.0,
            role="sanitario",
            status="en_terreno",
            callsign="ALFA-4",
            battery_pct=94,
            heart_rate_bpm=88,
            updated_at=now,
        ),
        "op_za_01": Operator(
            operator_id="op_za_01",
            name="Miguel Ángel Prieto",
            team_id="team_ume_zamora",
            lon=-3.1840,
            lat=41.2810,
            elevation_m=582.0,
            role="jefe_cuadrilla",
            status="en_terreno",
            callsign="BRAVO-1",
            battery_pct=89,
            heart_rate_bpm=102,
            updated_at=now,
        ),
        "op_za_02": Operator(
            operator_id="op_za_02",
            name="Laura Domínguez",
            team_id="team_ume_zamora",
            lon=-3.1805,
            lat=41.2832,
            elevation_m=590.0,
            role="piloto_dron",
            status="en_terreno",
            callsign="BRAVO-2",
            battery_pct=78,
            heart_rate_bpm=91,
            updated_at=now,
        ),
        "op_za_03": Operator(
            operator_id="op_za_03",
            name="David Alonso",
            team_id="team_ume_zamora",
            lon=-3.1872,
            lat=41.2794,
            elevation_m=574.0,
            role="brigadista",
            status="en_terreno",
            callsign="BRAVO-3",
            battery_pct=85,
            heart_rate_bpm=116,
            updated_at=now,
        ),
    }
    return teams, operators


class JuliTracker:
    """Controlador principal de JULI: mantiene equipos y operarios y exporta GeoJSON."""

    def __init__(
        self,
        state_path: str = config.DEFAULT_STATE_PATH,
        geojson_path: str = config.DEFAULT_GEOJSON_OUTPUT_PATH,
    ) -> None:
        self.state_path = state_path
        self.geojson_path = geojson_path
        self.teams: dict[str, Team] = {}
        self.operators: dict[str, Operator] = {}
        self._active_pol_alerts: dict[str, tuple[str, ...]] = {}
        self._load_or_init()

    def _load_or_init(self) -> None:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    raw = json.load(f)
                self.teams = {tid: Team(**tdata) for tid, tdata in raw.get("teams", {}).items()}
                self.operators = {
                    oid: Operator(
                        operator_id=odata["operator_id"],
                        name=odata["name"],
                        team_id=odata["team_id"],
                        lon=odata["lon"],
                        lat=odata["lat"],
                        elevation_m=odata.get("elevation_m", 0.0),
                        role=odata.get("role", "brigadista"),
                        status=odata.get("status", "en_terreno"),
                        callsign=odata.get("callsign", ""),
                        battery_pct=odata.get("battery_pct", 100),
                        heart_rate_bpm=odata.get("heart_rate_bpm"),
                        updated_at=odata.get("updated_at", _now_iso()),
                        last_moved_at=odata.get("last_moved_at", ""),
                        last_proof_of_life_at=odata.get("last_proof_of_life_at", ""),
                        radio_channel=odata.get("radio_channel", ""),
                        radio_frequency_mhz=odata.get("radio_frequency_mhz"),
                        talkgroup_id=odata.get("talkgroup_id", ""),
                        radio_protocol=odata.get("radio_protocol", config.RADIO_DEFAULT_PROTOCOL),
                        radio_device_id=odata.get("radio_device_id", ""),
                        radio_last_switch_at=odata.get("radio_last_switch_at", ""),
                    )
                    for oid, odata in raw.get("operators", {}).items()
                }
                for op in self.operators.values():
                    self._apply_team_radio_defaults(op)
                if not os.path.exists(self.geojson_path):
                    self.export_geojson()
                return
            except Exception as exc:
                _LOGGER.warning("Estado de tracker corrupto en %s: %s", self.state_path, exc)

        self.teams, self.operators = _default_seed_data()
        for op in self.operators.values():
            self._apply_team_radio_defaults(op)
        self.save_state()
        self.export_geojson()

    def _apply_team_radio_defaults(self, op: Operator) -> None:
        """Asigna por defecto canal/frecuencia/GSSI del escuadrón si el operario no los tiene."""
        plan = config.DEFAULT_TEAM_FREQUENCY_PLANS.get(op.team_id)
        team = self.teams.get(op.team_id)
        if not op.radio_channel:
            op.radio_channel = (
                str(plan["radio_channel"]) if plan else (team.radio_channel if team else "VHF-GEN")
            )
        if op.radio_frequency_mhz is None and plan:
            op.radio_frequency_mhz = float(plan["frequency_mhz"])
        if not op.talkgroup_id and plan:
            op.talkgroup_id = str(plan["talkgroup_id"])

    def save_state(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
        payload = {
            "algorithm": config.ALGORITHM_NAME,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "teams": {tid: t.to_dict() for tid, t in self.teams.items()},
            "operators": {oid: op.to_dict() for oid, op in self.operators.items()},
        }
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # -----------------------------------------------------------------------
    # Gestión de Equipos (Teams)
    # -----------------------------------------------------------------------
    def upsert_team(
        self,
        team_id: str,
        name: str,
        unit_code: str = "BRIF",
        vehicle_type: str = "Autobomba 4x4",
        radio_channel: str = "VHF-01",
        zone_assigned: str = "General",
        color: str | None = None,
    ) -> Team:
        assigned_color = color or config.TEAM_PALETTE[len(self.teams) % len(config.TEAM_PALETTE)]
        team = Team(
            team_id=team_id,
            name=name,
            unit_code=unit_code,
            vehicle_type=vehicle_type,
            radio_channel=radio_channel,
            zone_assigned=zone_assigned,
            color=assigned_color,
        )
        self.teams[team_id] = team
        self.save_state()
        self.export_geojson()
        return team

    def list_teams_with_members(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for tid, team in self.teams.items():
            members = [op.to_dict() for op in self.operators.values() if op.team_id == tid]
            result.append(
                {
                    **team.to_dict(),
                    "member_count": len(members),
                    "active_in_field_count": sum(
                        1 for m in members if m["status"] in ("en_terreno", "en_ruta", "alerta")
                    ),
                    "members": members,
                }
            )
        return result

    # -----------------------------------------------------------------------
    # Gestión de Operarios / Personas en un Equipo (Operators)
    # -----------------------------------------------------------------------
    def _apply_operator_position(
        self,
        op: Operator,
        lon: float,
        lat: float,
        timestamp: str,
        min_move_m: float = config.PROOF_OF_LIFE_MIN_MOVE_M,
    ) -> float:
        """Actualiza coordenadas y refresca `last_moved_at` solo si supera el umbral de jitter."""
        new_lon = round(float(lon), 6)
        new_lat = round(float(lat), 6)
        moved_m = _displacement_m(op.lon, op.lat, new_lon, new_lat)
        op.lon = new_lon
        op.lat = new_lat
        if moved_m >= min_move_m:
            op.last_moved_at = timestamp
            op.last_proof_of_life_at = timestamp
        return moved_m

    def sync_unit_position(
        self,
        operator_id: str,
        lon: float,
        lat: float,
        status: str,
        battery_pct: int,
        heart_rate_bpm: int | None,
        timestamp: str | None = None,
    ) -> Operator:
        """Sincroniza una unidad live manteniendo el seguimiento real de movimiento."""
        op = self.operators[operator_id]
        ts = timestamp or _now_iso()
        self._apply_operator_position(op, lon, lat, ts)
        op.status = status
        op.battery_pct = int(max(0, min(100, battery_pct)))
        op.heart_rate_bpm = heart_rate_bpm
        op.updated_at = ts
        return op

    def upsert_operator(
        self,
        operator_id: str | None,
        name: str,
        team_id: str,
        lon: float | None = None,
        lat: float | None = None,
        elevation_m: float = 0.0,
        role: str = "brigadista",
        status: str = "en_terreno",
        callsign: str = "",
        battery_pct: int = 100,
        heart_rate_bpm: int | None = None,
        quadrant_id: str | None = None,
        offset_x_m: float | None = None,
        offset_y_m: float | None = None,
        sub_x_norm: float | None = None,
        sub_y_norm: float | None = None,
    ) -> Operator:
        if (lon is None or lat is None) and quadrant_id:
            lon, lat = quadrant_subcoords_to_lonlat(
                quadrant_id=quadrant_id,
                offset_x_m=offset_x_m,
                offset_y_m=offset_y_m,
                sub_x_norm=sub_x_norm,
                sub_y_norm=sub_y_norm,
            )
        if lon is None or lat is None:
            raise ValueError("Se requiere (lon, lat) o (quadrant_id + subcoordenadas).")

        oid = operator_id or f"op_{len(self.operators) + 1:03d}"
        # Si el equipo no existe, se crea automáticamente para evitar operarios huérfanos
        if team_id not in self.teams:
            self.teams[team_id] = Team(
                team_id=team_id,
                name=f"Equipo {team_id}",
                color=config.TEAM_PALETTE[len(self.teams) % len(config.TEAM_PALETTE)],
            )

        now_str = _now_iso()
        existing = self.operators.get(oid)
        if existing is not None:
            last_moved_at = existing.last_moved_at
            last_pol_at = existing.last_proof_of_life_at
            if (
                _displacement_m(existing.lon, existing.lat, float(lon), float(lat))
                >= config.PROOF_OF_LIFE_MIN_MOVE_M
            ):
                last_moved_at = now_str
                last_pol_at = now_str
        else:
            last_moved_at = now_str
            last_pol_at = now_str

        op = Operator(
            operator_id=oid,
            name=name,
            team_id=team_id,
            lon=round(float(lon), 6),
            lat=round(float(lat), 6),
            elevation_m=round(float(elevation_m), 1),
            role=role,
            status=status,
            callsign=callsign or oid.upper(),
            battery_pct=int(max(0, min(100, battery_pct))),
            heart_rate_bpm=heart_rate_bpm,
            updated_at=now_str,
            last_moved_at=last_moved_at,
            last_proof_of_life_at=last_pol_at,
            radio_channel=existing.radio_channel
            if existing and existing.team_id == team_id
            else "",
            radio_frequency_mhz=existing.radio_frequency_mhz
            if existing and existing.team_id == team_id
            else None,
            talkgroup_id=existing.talkgroup_id if existing and existing.team_id == team_id else "",
            radio_protocol=existing.radio_protocol if existing else config.RADIO_DEFAULT_PROTOCOL,
            radio_device_id=existing.radio_device_id if existing else "",
            radio_last_switch_at=existing.radio_last_switch_at if existing else "",
        )
        self._apply_team_radio_defaults(op)
        self.operators[oid] = op
        self.save_state()
        self.export_geojson()
        return op

    def update_operator_location(
        self,
        operator_id: str,
        lon: float | None = None,
        lat: float | None = None,
        elevation_m: float | None = None,
        status: str | None = None,
        battery_pct: int | None = None,
        heart_rate_bpm: int | None = None,
        team_id: str | None = None,
        quadrant_id: str | None = None,
        offset_x_m: float | None = None,
        offset_y_m: float | None = None,
        sub_x_norm: float | None = None,
        sub_y_norm: float | None = None,
    ) -> Operator:
        if operator_id not in self.operators:
            raise KeyError(f"No existe el operario '{operator_id}' en JULI.")
        op = self.operators[operator_id]
        now_str = _now_iso()
        if (lon is None or lat is None) and quadrant_id:
            lon, lat = quadrant_subcoords_to_lonlat(
                quadrant_id=quadrant_id,
                offset_x_m=offset_x_m,
                offset_y_m=offset_y_m,
                sub_x_norm=sub_x_norm,
                sub_y_norm=sub_y_norm,
            )
        if lon is not None and lat is not None:
            self._apply_operator_position(op, lon, lat, now_str)
        if team_id is not None:
            op.team_id = team_id
        if elevation_m is not None:
            op.elevation_m = round(float(elevation_m), 1)
        if status is not None:
            op.status = status
        if battery_pct is not None:
            op.battery_pct = int(max(0, min(100, battery_pct)))
        if heart_rate_bpm is not None:
            op.heart_rate_bpm = heart_rate_bpm
        op.updated_at = now_str
        self.save_state()
        self.export_geojson()
        return op

    def confirm_proof_of_life(
        self,
        operator_id: str,
        lon: float | None = None,
        lat: float | None = None,
        elevation_m: float | None = None,
        status: str | None = None,
        battery_pct: int | None = None,
        heart_rate_bpm: int | None = None,
        note: str = "",
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Registra confirmación explícita de prueba de vida del operario."""
        if operator_id not in self.operators:
            raise KeyError(f"No existe el operario '{operator_id}' en JULI.")
        op = self.operators[operator_id]
        ts = timestamp or _now_iso()
        if lon is not None and lat is not None:
            self._apply_operator_position(op, lon, lat, ts)
        if elevation_m is not None:
            op.elevation_m = round(float(elevation_m), 1)
        if status is not None:
            op.status = status
        if battery_pct is not None:
            op.battery_pct = int(max(0, min(100, battery_pct)))
        if heart_rate_bpm is not None:
            op.heart_rate_bpm = heart_rate_bpm
        op.last_proof_of_life_at = ts
        op.updated_at = ts
        self.save_state()
        self.export_geojson()
        return {
            "operator": op.to_dict(),
            "last_location": op.last_location_payload(_parse_iso(ts)),
            "confirmed_at": ts,
            "note": note,
        }

    def reassign_operator_team(
        self,
        operator_id: str,
        new_team_id: str,
        *,
        radio_channel: str,
        radio_frequency_mhz: float,
        talkgroup_id: str,
        radio_protocol: str = config.RADIO_DEFAULT_PROTOCOL,
        radio_device_id: str = "",
        switched_at: str | None = None,
    ) -> Operator:
        """Cambia atómicamente al operario de escuadrón al sintonizar otra frecuencia de radio."""
        if operator_id not in self.operators:
            raise KeyError(f"No existe el operario '{operator_id}' en JULI.")
        if new_team_id not in self.teams:
            raise KeyError(f"No existe el equipo destino '{new_team_id}' en JULI.")
        op = self.operators[operator_id]
        ts = switched_at or _now_iso()
        op.team_id = new_team_id
        op.radio_channel = radio_channel
        op.radio_frequency_mhz = round(float(radio_frequency_mhz), 4)
        op.talkgroup_id = str(talkgroup_id)
        op.radio_protocol = radio_protocol
        if radio_device_id:
            op.radio_device_id = radio_device_id
        op.radio_last_switch_at = ts
        op.updated_at = ts
        self.save_state()
        self.export_geojson()
        return op

    def remove_operator(self, operator_id: str) -> bool:
        if operator_id not in self.operators:
            return False
        del self.operators[operator_id]
        self._active_pol_alerts.pop(operator_id, None)
        self.save_state()
        self.export_geojson()
        return True

    # -----------------------------------------------------------------------
    # Prueba de Vida (Proof of Life): inmovilidad >= 15 min o cuadrante ardiendo
    # -----------------------------------------------------------------------
    def evaluate_proof_of_life(
        self,
        now: datetime | None = None,
        immobile_seconds: int = config.PROOF_OF_LIFE_IMMOBILE_SECONDS,
        cata_predictions_path: str | None = None,
    ) -> dict[str, Any]:
        """Evalúa todos los operarios y genera avisos para Central y su escuadrón."""
        now_dt = _now_utc(now)
        checked_at = _now_iso(now_dt)
        burning_quadrants = load_burning_quadrants(cata_predictions_path)

        alerts: list[dict[str, Any]] = []
        statuses_by_operator: dict[str, dict[str, Any]] = {}

        for op in self.operators.values():
            last_location = op.last_location_payload(now_dt)
            pol_dt = (
                _parse_iso(op.last_proof_of_life_at)
                or _parse_iso(op.last_moved_at)
                or _parse_iso(op.updated_at)
                or now_dt
            )
            seconds_since_proof = max(0, int((now_dt - pol_dt).total_seconds()))
            is_immobile = (
                op.status not in config.PROOF_OF_LIFE_INACTIVE_IMMOBILE_STATUSES
                and seconds_since_proof >= immobile_seconds
            )

            qid = last_location["quadrant_id"]
            fire_cell = burning_quadrants.get(qid)
            is_quadrant_burning = fire_cell is not None

            reasons: list[str] = []
            if is_immobile:
                reasons.append("immobile_timeout")
            if is_quadrant_burning:
                reasons.append("quadrant_burning")

            triggered = bool(reasons)
            statuses_by_operator[op.operator_id] = {
                "operator_id": op.operator_id,
                "triggered": triggered,
                "reasons": reasons,
                "immobile_seconds": last_location["immobile_seconds"],
                "seconds_since_proof": seconds_since_proof,
                "quadrant_burning": is_quadrant_burning,
                "last_location": last_location,
            }
            if not triggered:
                continue

            team = self.teams.get(op.team_id)
            squadron_mates = [
                {
                    "operator_id": mate.operator_id,
                    "name": mate.name,
                    "callsign": mate.callsign,
                    "role": mate.role,
                    "status": mate.status,
                }
                for mate in self.operators.values()
                if mate.team_id == op.team_id and mate.operator_id != op.operator_id
            ]

            priority = "critical" if is_quadrant_burning else "high"
            reason_msgs: list[str] = []
            if is_immobile:
                mins = last_location["immobile_seconds"] // 60
                reason_msgs.append(f"sin movimiento desde hace {mins} min")
            if is_quadrant_burning:
                state_lbl = (fire_cell or {}).get(
                    "state_label"
                ) or f"estado {fire_cell['quadrant_state']}"
                reason_msgs.append(f"cuadrante {qid} en llamas ({state_lbl})")

            summary = (
                f"PRUEBA DE VIDA [{op.callsign or op.operator_id} - {op.name}]: "
                f"{' y '.join(reason_msgs)}. "
                f"Última localización: {qid} ({last_location['sub_cell_id']}, "
                f"lon={last_location['lon']}, lat={last_location['lat']})."
            )

            alerts.append(
                {
                    "event": "proof_of_life_alert",
                    "priority": priority,
                    "triggered_at": checked_at,
                    "operator_id": op.operator_id,
                    "name": op.name,
                    "callsign": op.callsign,
                    "role": op.role,
                    "status": op.status,
                    "reasons": reasons,
                    "summary": summary,
                    # Campo prioritario solicitado: última localización exacta del operario
                    "last_location": last_location,
                    "fire_context": fire_cell,
                    "recipients": {
                        "central": {
                            "target": "central",
                            "channel": "CENTRAL_COMMAND",
                            "priority": priority,
                            "notified": True,
                        },
                        "squadron": {
                            "team_id": op.team_id,
                            "team_name": team.name if team else op.team_id,
                            "unit_code": team.unit_code if team else "",
                            "radio_channel": team.radio_channel if team else "",
                            "members_count": len(squadron_mates),
                            "member_ids": [m["operator_id"] for m in squadron_mates],
                            "members": squadron_mates,
                        },
                    },
                }
            )

        return {
            "checked_at": checked_at,
            "immobile_threshold_seconds": immobile_seconds,
            "burning_quadrants_count": len(burning_quadrants),
            "total_operators": len(self.operators),
            "active_alerts_count": len(alerts),
            "alerts": alerts,
            "statuses_by_operator": statuses_by_operator,
        }

    def poll_proof_of_life_events(
        self,
        now: datetime | None = None,
        immobile_seconds: int = config.PROOF_OF_LIFE_IMMOBILE_SECONDS,
        cata_predictions_path: str | None = None,
    ) -> dict[str, Any]:
        """Detecta transiciones (nuevas alertas o resoluciones) para evitar spam en WebSocket."""
        evaluation = self.evaluate_proof_of_life(
            now=now,
            immobile_seconds=immobile_seconds,
            cata_predictions_path=cata_predictions_path,
        )
        current_by_id = {a["operator_id"]: a for a in evaluation["alerts"]}
        events: list[dict[str, Any]] = []
        new_alerts: list[dict[str, Any]] = []
        resolved_operator_ids: list[str] = []

        for oid, alert in current_by_id.items():
            prev_reasons = set(self._active_pol_alerts.get(oid, ()))
            curr_reasons = tuple(sorted(alert["reasons"]))
            if set(curr_reasons) - prev_reasons:
                events.append(alert)
                new_alerts.append(alert)
            self._active_pol_alerts[oid] = curr_reasons

        for oid in list(self._active_pol_alerts):
            if oid not in current_by_id:
                del self._active_pol_alerts[oid]
                resolved_operator_ids.append(oid)
                op = self.operators.get(oid)
                events.append(
                    {
                        "event": "proof_of_life_resolved",
                        "resolved_at": evaluation["checked_at"],
                        "operator_id": oid,
                        "team_id": op.team_id if op else None,
                        "last_location": op.last_location_payload(now) if op else None,
                    }
                )

        return {
            "events": events,
            "new_alerts": new_alerts,
            "resolved_operator_ids": resolved_operator_ids,
            "evaluation": evaluation,
        }

    # -----------------------------------------------------------------------
    # Construcción y exportación de GeoJSON (WGS84 / RFC 7946) para el Frontend
    # -----------------------------------------------------------------------
    def build_geojson(
        self,
        team_filter: str | None = None,
        status_filter: str | None = None,
        include_team_features: bool = True,
    ) -> dict[str, Any]:
        """Genera el `FeatureCollection` GeoJSON de operarios y equipos en el terreno."""
        pol_eval = self.evaluate_proof_of_life()
        pol_statuses = pol_eval["statuses_by_operator"]

        features: list[dict[str, Any]] = []
        filtered_ops: list[Operator] = []

        for op in self.operators.values():
            if team_filter and op.team_id != team_filter:
                continue
            if status_filter and op.status != status_filter:
                continue
            filtered_ops.append(op)

        # 1. Features Point de cada operario individual en el terreno
        for op in filtered_ops:
            team = self.teams.get(op.team_id)
            team_name = team.name if team else op.team_id
            team_color = team.color if team else "#06b6d4"
            status_color = config.STATUS_COLORS.get(op.status, "#10b981")
            loc = op.quadrant_location()
            op_pol = pol_statuses.get(op.operator_id, {})

            features.append(
                {
                    "type": "Feature",
                    "id": f"juli_operator_{op.operator_id}",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [op.lon, op.lat, op.elevation_m],
                    },
                    "properties": {
                        "feature_type": "field_operator",
                        "algorithm": config.ALGORITHM_NAME,
                        "operator_id": op.operator_id,
                        "name": op.name,
                        "callsign": op.callsign,
                        "role": op.role,
                        "role_label": config.ROLE_LABELS.get(op.role, op.role),
                        "status": op.status,
                        "team_id": op.team_id,
                        "team_name": team_name,
                        "unit_code": team.unit_code if team else "",
                        "vehicle_type": team.vehicle_type if team else "",
                        "radio_channel": op.radio_channel or (team.radio_channel if team else ""),
                        "radio_frequency_mhz": op.radio_frequency_mhz,
                        "talkgroup_id": op.talkgroup_id,
                        "radio_protocol": op.radio_protocol,
                        "radio_device_id": op.radio_device_id,
                        "radio_last_switch_at": op.radio_last_switch_at,
                        "zone_assigned": team.zone_assigned if team else "",
                        "lon": op.lon,
                        "lat": op.lat,
                        "elevation_m": op.elevation_m,
                        **loc,
                        "quadrant_location": loc,
                        "battery_pct": op.battery_pct,
                        "heart_rate_bpm": op.heart_rate_bpm,
                        "updated_at": op.updated_at,
                        "last_moved_at": op.last_moved_at,
                        "last_proof_of_life_at": op.last_proof_of_life_at,
                        "immobile_seconds": op_pol.get("immobile_seconds", 0),
                        "proof_of_life_alert": bool(op_pol.get("triggered", False)),
                        "proof_of_life_reasons": op_pol.get("reasons", []),
                        "marker_color": status_color,
                        "team_color": team_color,
                        "marker_symbol": ("star" if op.role == "jefe_cuadrilla" else "person"),
                    },
                }
            )

        # 2. Features de agrupación por Equipo (centroide del equipo + línea de cohesión del equipo)
        teams_summary: list[dict[str, Any]] = []
        for tid, team in self.teams.items():
            if team_filter and tid != team_filter:
                continue
            team_ops = [op for op in filtered_ops if op.team_id == tid]
            if not team_ops:
                continue

            mean_lon = round(sum(o.lon for o in team_ops) / len(team_ops), 6)
            mean_lat = round(sum(o.lat for o in team_ops) / len(team_ops), 6)
            mean_elev = round(sum(o.elevation_m for o in team_ops) / len(team_ops), 1)
            team_loc = lonlat_to_quadrant_subcoords(mean_lon, mean_lat)
            leader = next(
                (o.name for o in team_ops if o.role == "jefe_cuadrilla"),
                team_ops[0].name,
            )

            teams_summary.append(
                {
                    "team_id": tid,
                    "name": team.name,
                    "unit_code": team.unit_code,
                    "zone_assigned": team.zone_assigned,
                    "radio_channel": team.radio_channel,
                    "leader_name": leader,
                    "members_count": len(team_ops),
                    "member_ids": [o.operator_id for o in team_ops],
                    "centroid_lonlat": [mean_lon, mean_lat],
                    "quadrant_id": team_loc["quadrant_id"],
                    "quadrant_location": team_loc,
                    "color": team.color,
                }
            )

            if include_team_features:
                features.append(
                    {
                        "type": "Feature",
                        "id": f"juli_team_centroid_{tid}",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [mean_lon, mean_lat, mean_elev],
                        },
                        "properties": {
                            "feature_type": "field_team_centroid",
                            "algorithm": config.ALGORITHM_NAME,
                            "team_id": tid,
                            "name": team.name,
                            "unit_code": team.unit_code,
                            "vehicle_type": team.vehicle_type,
                            "radio_channel": team.radio_channel,
                            "zone_assigned": team.zone_assigned,
                            "leader_name": leader,
                            "members_count": len(team_ops),
                            "member_names": [o.name for o in team_ops],
                            "elevation_m": mean_elev,
                            **team_loc,
                            "quadrant_location": team_loc,
                            "fill_color": team.color,
                            "marker_symbol": "users",
                        },
                    }
                )

                if len(team_ops) >= 2:
                    link_coords = [[o.lon, o.lat, o.elevation_m] for o in team_ops]
                    if len(team_ops) >= 3:
                        link_coords.append(link_coords[0])
                    features.append(
                        {
                            "type": "Feature",
                            "id": f"juli_team_link_{tid}",
                            "geometry": {
                                "type": "LineString",
                                "coordinates": link_coords,
                            },
                            "properties": {
                                "feature_type": "field_team_formation",
                                "algorithm": config.ALGORITHM_NAME,
                                "team_id": tid,
                                "team_name": team.name,
                                "unit_code": team.unit_code,
                                "members_count": len(team_ops),
                                "stroke_color": team.color,
                                "stroke_width": 2,
                                "stroke_opacity": 0.75,
                            },
                        }
                    )

        return {
            "type": "FeatureCollection",
            "metadata": {
                "algorithm": config.ALGORITHM_NAME,
                "description": "Control live de equipos y operarios desplegados en terreno",
                "independent_from_pipeline": True,
                "crs": config.OUTPUT_GEOJSON_CRS,
                "quadrant_grid": {
                    "crs": config.GRID_CRS,
                    "cell_prefix": config.CELL_PREFIX,
                    "grid_level": config.GRID_LEVEL,
                    "cell_size_m": config.CELL_SIZE_M,
                },
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "total_teams": len(teams_summary),
                "total_operators": len(filtered_ops),
                "operators_by_status": {
                    st: sum(1 for o in filtered_ops if o.status == st)
                    for st in config.STATUS_COLORS
                },
                "proof_of_life": {
                    "checked_at": pol_eval["checked_at"],
                    "immobile_threshold_seconds": pol_eval["immobile_threshold_seconds"],
                    "active_alerts_count": pol_eval["active_alerts_count"],
                    "alerts": pol_eval["alerts"],
                },
                "frontend_style_guide": {
                    "field_operator": {
                        "status_colors": config.STATUS_COLORS,
                        "symbol_leader": "star",
                        "symbol_member": "person",
                    },
                    "field_team_centroid": {
                        "symbol": "users",
                        "label": "Posición Media de Cuadrilla / Equipo",
                    },
                    "field_team_formation": {
                        "width": 2,
                        "opacity": 0.75,
                        "label": "Enlace de Cohesión del Equipo",
                    },
                },
                "teams": teams_summary,
            },
            "features": features,
        }

    def export_geojson(self, output_path: str | None = None) -> dict[str, Any]:
        target_path = output_path or self.geojson_path
        payload = self.build_geojson()
        if target_path:
            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        return payload


# Instancia singleton lista para usar desde FastAPI o scripts
juli_tracker = JuliTracker()
