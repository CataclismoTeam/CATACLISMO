"""JULI — Sistema independiente de control en tiempo real de equipos y operarios en el terreno."""

from .config import (
    ALGORITHM_NAME,
    DEFAULT_GEOJSON_OUTPUT_PATH,
    DEFAULT_STATE_PATH,
    OUTPUT_GEOJSON_CRS,
    ROLE_LABELS,
    STATUS_COLORS,
    TEAM_PALETTE,
    OperatorRole,
    OperatorStatus,
)
from .tracker import JuliTracker, Operator, Team, juli_tracker

__all__ = [
    "ALGORITHM_NAME",
    "OUTPUT_GEOJSON_CRS",
    "DEFAULT_STATE_PATH",
    "DEFAULT_GEOJSON_OUTPUT_PATH",
    "STATUS_COLORS",
    "ROLE_LABELS",
    "TEAM_PALETTE",
    "OperatorStatus",
    "OperatorRole",
    "Operator",
    "Team",
    "JuliTracker",
    "juli_tracker",
]
