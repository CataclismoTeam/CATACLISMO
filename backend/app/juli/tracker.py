"""Gestor de equipos y operarios en terreno de JULI con exportación GeoJSON (WGS84 / RFC 7946).

JULI es un módulo independiente de la pipeline VALEN -> CATA -> LUCIA dedicado a llevar el
control actualizado de los equipos de intervención y de cada operario desplegado en el terreno,
devolviendo su posición y telemetría en formato GeoJSON listo para el Frontend (CesiumJS / deck.gl).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import time
from typing import Any

from . import config


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
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"))


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
        self._load_or_init()

    def _load_or_init(self) -> None:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    raw = json.load(f)
                self.teams = {
                    tid: Team(**tdata) for tid, tdata in raw.get("teams", {}).items()
                }
                self.operators = {
                    oid: Operator(**odata)
                    for oid, odata in raw.get("operators", {}).items()
                }
                if not os.path.exists(self.geojson_path):
                    self.export_geojson()
                return
            except Exception:
                pass

        self.teams, self.operators = _default_seed_data()
        self.save_state()
        self.export_geojson()

    def save_state(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
        payload = {
            "algorithm": config.ALGORITHM_NAME,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "teams": {tid: asdict(t) for tid, t in self.teams.items()},
            "operators": {oid: asdict(op) for oid, op in self.operators.items()},
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
            members = [
                asdict(op) for op in self.operators.values() if op.team_id == tid
            ]
            result.append(
                {
                    **asdict(team),
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
    def upsert_operator(
        self,
        operator_id: str,
        name: str,
        team_id: str,
        lon: float,
        lat: float,
        elevation_m: float = 0.0,
        role: str = "brigadista",
        status: str = "en_terreno",
        callsign: str = "",
        battery_pct: int = 100,
        heart_rate_bpm: int | None = None,
    ) -> Operator:
        # Si el equipo aún no existe, se crea automáticamente para que ningún operario quede huérfano
        if team_id not in self.teams:
            self.teams[team_id] = Team(
                team_id=team_id,
                name=f"Equipo {team_id}",
                color=config.TEAM_PALETTE[len(self.teams) % len(config.TEAM_PALETTE)],
            )

        op = Operator(
            operator_id=operator_id,
            name=name,
            team_id=team_id,
            lon=round(float(lon), 6),
            lat=round(float(lat), 6),
            elevation_m=round(float(elevation_m), 1),
            role=role,
            status=status,
            callsign=callsign or operator_id.upper(),
            battery_pct=int(max(0, min(100, battery_pct))),
            heart_rate_bpm=heart_rate_bpm,
            updated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )
        self.operators[operator_id] = op
        self.save_state()
        self.export_geojson()
        return op

    def update_operator_location(
        self,
        operator_id: str,
        lon: float,
        lat: float,
        elevation_m: float | None = None,
        status: str | None = None,
        battery_pct: int | None = None,
        heart_rate_bpm: int | None = None,
    ) -> Operator:
        if operator_id not in self.operators:
            raise KeyError(f"No existe el operario '{operator_id}' en JULI.")
        op = self.operators[operator_id]
        op.lon = round(float(lon), 6)
        op.lat = round(float(lat), 6)
        if elevation_m is not None:
            op.elevation_m = round(float(elevation_m), 1)
        if status is not None:
            op.status = status
        if battery_pct is not None:
            op.battery_pct = int(max(0, min(100, battery_pct)))
        if heart_rate_bpm is not None:
            op.heart_rate_bpm = heart_rate_bpm
        op.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.save_state()
        self.export_geojson()
        return op

    def remove_operator(self, operator_id: str) -> bool:
        if operator_id not in self.operators:
            return False
        del self.operators[operator_id]
        self.save_state()
        self.export_geojson()
        return True

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
                        "radio_channel": team.radio_channel if team else "",
                        "zone_assigned": team.zone_assigned if team else "",
                        "elevation_m": op.elevation_m,
                        "battery_pct": op.battery_pct,
                        "heart_rate_bpm": op.heart_rate_bpm,
                        "updated_at": op.updated_at,
                        "marker_color": status_color,
                        "team_color": team_color,
                        "marker_symbol": (
                            "star" if op.role == "jefe_cuadrilla" else "person"
                        ),
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
                "description": "Control en tiempo real de equipos y operarios desplegados en el terreno",
                "independent_from_pipeline": True,
                "crs": config.OUTPUT_GEOJSON_CRS,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "total_teams": len(teams_summary),
                "total_operators": len(filtered_ops),
                "operators_by_status": {
                    st: sum(1 for o in filtered_ops if o.status == st)
                    for st in config.STATUS_COLORS
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
