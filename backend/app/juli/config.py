"""Configuración del sistema JULI — Control en tiempo real de equipos y operarios en el terreno."""

from __future__ import annotations

import os
from typing import Literal

ALGORITHM_NAME: str = "juli"
OUTPUT_GEOJSON_CRS: str = "EPSG:4326"

OperatorStatus = Literal["en_terreno", "en_ruta", "en_descanso", "alerta", "inactivo"]
OperatorRole = Literal[
    "jefe_cuadrilla",
    "brigadista",
    "conductor_autobomba",
    "sanitario",
    "piloto_dron",
    "coordinador",
]

STATUS_COLORS: dict[str, str] = {
    "en_terreno": "#10b981",   # Verde esmeralda: operativo en misión
    "en_ruta": "#3b82f6",      # Azul: desplazándose
    "en_descanso": "#a855f7",  # Violeta: relevo / base
    "alerta": "#ef4444",       # Rojo: emergencia / SOS del operario
    "inactivo": "#6b7280",     # Gris: fuera de turno
}

ROLE_LABELS: dict[str, str] = {
    "jefe_cuadrilla": "Jefe de Cuadrilla",
    "brigadista": "Brigadista Forestal",
    "conductor_autobomba": "Conductor Autobomba",
    "sanitario": "Sanitario / Apoyo Vital",
    "piloto_dron": "Operador Dron Térmico",
    "coordinador": "Coordinador de Puesto de Mando",
}

TEAM_PALETTE: tuple[str, ...] = (
    "#06b6d4",  # Cyan
    "#f59e0b",  # Amber
    "#8b5cf6",  # Purple
    "#ec4899",  # Pink
    "#14b8a6",  # Teal
    "#eab308",  # Yellow
)

_JULI_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACT_DIR: str = os.path.join(_JULI_DIR, "artifacts")
STATE_DIR: str = os.path.join(ARTIFACT_DIR, "state")
GEOJSON_DIR: str = os.path.join(ARTIFACT_DIR, "geojson")

DEFAULT_STATE_PATH: str = os.path.join(STATE_DIR, "juli_state.json")
DEFAULT_GEOJSON_OUTPUT_PATH: str = os.path.join(GEOJSON_DIR, "juli_operators.geojson")
