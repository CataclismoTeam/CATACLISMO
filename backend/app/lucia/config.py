"""Configuración central e invariantes del algoritmo LUCIA.

LUCIA es el tercer eslabón de la pipeline **VALEN -> CATA -> LUCIA**:
  1. **VALEN** (`backend/app/valen/`): Ingesta, proyecta (EPSG:3035 `ES1K`),
     enriquece (Meteo, Rainfall, Vegetation) y valida detecciones satelitales.
  2. **CATA** (`backend/app/cata/`): Red ConvLSTM de 22 canales que predice
     la propagación del fuego en `t+1` y exporta `cata_predictions.json`.
  3. **LUCIA** (`backend/app/lucia/`): Modelo modular en TensorFlow/Keras + motor
     A* espacio-temporal que calcula el camino más corto y seguro hacia una
     **zona libre de peligro** para personas y animales, teniendo en cuenta:
       - Zonas **ya quemadas** (`CONFIRMED_BURNED` / `'F'`).
       - Zonas **quemándose activamente o de ignición inminente** (`CONFIRMED_AND_CONTINUES` / `'B'`, `PREDICTED_FIRE` / `'P'`).
       - Zonas **sin quemar** (`SAFE` / `'.'`) filtradas mediante un **threshold seguro al fuego** (`SAFE_FIRE_THRESHOLD`).
     Exporta las rutas y zonas en formato **GeoJSON (WGS84 / EPSG:4326)** listo para el Frontend (CesiumJS / deck.gl).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Identificadores de la pipeline VALEN -> CATA -> LUCIA
# ---------------------------------------------------------------------------
ALGORITHM_NAME: str = "lucia"
SOURCE_PREDICTION_ALGORITHM: str = "cata"
SOURCE_VALIDATION_ALGORITHM: str = "valen"
PIPELINE_CHAIN: tuple[str, str, str] = ("valen", "cata", "lucia")

# ---------------------------------------------------------------------------
# Geometría de la rejilla heredada de VALEN / CATA (EPSG:3035 -> WGS84)
# ---------------------------------------------------------------------------
GRID_ID: str = "ES-LAEA-1K-v1"
GRID_CRS: str = "EPSG:3035"
OUTPUT_GEOJSON_CRS: str = "EPSG:4326"
GRID_LEVEL: int = 0
CELL_PREFIX: str = "ES1K"
CELL_SIZE_M: float = 1000.0
GRID_SIZE: int = 32

# ---------------------------------------------------------------------------
# Estados de celda procedentes de CATA y clasificación térmica de LUCIA
# ---------------------------------------------------------------------------
QUADRANT_STATE_SAFE: int = 0          # '.' -> Sin quemar
QUADRANT_STATE_PREDICTED: int = 1     # 'P' -> Predicción de nuevo fuego en t+1
QUADRANT_STATE_BURNED_REAL: int = 2   # 'F' -> Ya quemado (confirmado por satélite)
QUADRANT_STATE_PERSISTENT: int = 3    # 'B' -> Quemándose activamente y continúa en t+1

# Categorías semánticas de peligro térmico que LUCIA distingue explícitamente
FIRE_ZONE_SAFE_UNBURNED: str = "SAFE_UNBURNED"                  # Sin quemar y por debajo del threshold seguro
FIRE_ZONE_THRESHOLD_BUFFER: str = "THRESHOLD_BUFFER_UNSAFE"     # Sin quemar pero supera el threshold seguro al fuego
FIRE_ZONE_ALREADY_BURNED: str = "ALREADY_BURNED"                # Ya quemado (estado 2='F': brasas, humo, caída árboles)
FIRE_ZONE_BURNING_ACTIVE: str = "BURNING_ACTIVE"                # Quemándose ahora o en ignición (estados 3='B' y 1='P')

# ---------------------------------------------------------------------------
# Umbrales de seguridad frente al fuego (configurables)
# ---------------------------------------------------------------------------
# Threshold seguro al fuego: cualquier celda sin quemar cuya probabilidad de fuego
# predicha por CATA supere este valor se descarta como ruta segura (más estricto que el 0.50 de CATA).
SAFE_FIRE_THRESHOLD: float = 0.25

# Probabilidad máxima permitida en la celda destino ("zona libre de peligro / refugio")
SAFE_HAVEN_MAX_PROB: float = 0.10

# Distancia mínima (en celdas de 1 km) desde la "zona libre de peligro" a cualquier foco quemado/ardiendo
MIN_SAFE_DISTANCE_CELLS: float = 3.0

# Margen temporal mínimo (en horas) entre la llegada del evacuado a una celda y la llegada del fuego
SAFETY_TIME_MARGIN_HOURS: float = 1.5

# Velocidades medias de evacuación en terreno base (km/h)
HUMAN_BASE_SPEED_KMH: float = 4.5
ANIMAL_BASE_SPEED_KMH: float = 6.0

# ---------------------------------------------------------------------------
# Registro canónico de canales del modelo TensorFlow de LUCIA (C = 15)
# ---------------------------------------------------------------------------
# Soporta expansión modular de canales (`expand_lucia_channels`) igual que CATA.
LUCIA_CHANNEL_REGISTRY: tuple[str, ...] = (
    # --- Bloque 1: Estado de quemado y predicción de CATA (canales 0..5) ---
    "is_safe_unburned",       # 0: 1.0 si sin quemar y prob_t1 < safe_fire_threshold
    "is_burning_active",      # 1: 1.0 si quemándose activo (estado 3='B' o 1='P')
    "is_already_burned",      # 2: 1.0 si ya quemado (estado 2='F')
    "fire_probability_t1",    # 3: Probabilidad continua [0, 1] predicha por CATA
    "fire_proximity_risk",    # 4: exp(-distancia_euclidea_al_fuego / 3.0)
    "arrival_urgency",        # 5: 1.0 - clip(estimated_fire_arrival_hours / 24.0, 0, 1)
    # --- Bloque 2: Costes físicos y variables ambientales de VALEN (canales 6..11) ---
    "human_base_cost_norm",   # 6: Coste físico humano de CATA normalizado a [0, 1]
    "animal_base_cost_norm",  # 7: Coste físico animal de CATA normalizado a [0, 1]
    "veg_flammability",       # 8: Inflamabilidad vegetal VALEN (WorldCover + IFN3)
    "meteo_wind_speed",       # 9: Velocidad del viento VALEN (Meteomatics)
    "meteo_fwi_temp",         # 10: Índice FWI / temperatura VALEN combinados
    "border_escape_affinity", # 11: Afinidad espacial hacia zonas exteriores despejadas
    # --- Bloque 3: Red viaria OSM de VALEN (canal 12) ---
    "road_access",            # 12: road_access_score VALEN/OSM (densidad viaria ponderada, [0, 1])
    # --- Bloque 4: Topografía y elevación Open-Elevation de VALEN (canales 13..14) ---
    "elevation_norm",         # 13: Altitud relativa normalizada en la zona [0, 1] (Open-Elevation)
    "slope_steepness",        # 14: Pendiente topográfica normalizada [0, 1] (slope_pct / 35.0)
)

BASE_NUM_CHANNELS: int = 6
DEFAULT_NUM_CHANNELS: int = len(LUCIA_CHANNEL_REGISTRY)  # 15 canales
OUTPUT_HEAD_CHANNELS: int = 3  # (0: human_risk_cost, 1: animal_risk_cost, 2: safe_haven_score)

# Configuración de Puntos de Encuentro (Meeting Points) explícitos
DEFAULT_MEETING_POINTS_PER_ZONE: int = 3
MEETING_POINT_MAX_SLOPE_PCT: float = 12.0

# ---------------------------------------------------------------------------
# Hiperparámetros del modelo TensorFlow de LUCIA
# ---------------------------------------------------------------------------
CONV_FILTERS: tuple[int, ...] = (32, 64, 32)
KERNEL_SIZE: tuple[int, int] = (3, 3)
DROPOUT_RATE: float = 0.15
LEARNING_RATE: float = 1e-3
FINETUNE_LR: float = 3e-4
EXPAND_LR: float = 5e-4
BATCH_SIZE: int = 8
EPOCHS: int = 12
SEED: int = 42

# ---------------------------------------------------------------------------
# Rutas por defecto de entrada (CATA) y salida (LUCIA GeoJSON + Modelo)
# ---------------------------------------------------------------------------
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_MODULE_DIR)

DEFAULT_CATA_PREDICTIONS_PATH: str = os.path.join(
    _APP_DIR, "cata", "artifacts", "predictions", "cata_predictions.json"
)
# Red viaria OSM rasterizada por VALEN (`python -m app.valen.roads_client --from-cata ...`)
DEFAULT_VALEN_ROADS_PATH: str = os.path.join(_APP_DIR, "valen", "output", "cell_roads.json")
# Elevación y pendientes Open-Elevation de VALEN (`python -m app.valen.elevation_client --from-cata ...`)
DEFAULT_VALEN_ELEVATION_PATH: str = os.path.join(_APP_DIR, "valen", "output", "cell_elevation.json")
# Si una zona no está en cell_roads.json, LUCIA puede pedir a VALEN que la descargue de OSM al vuelo
FETCH_MISSING_ROADS_ONLINE: bool = os.environ.get("LUCIA_FETCH_ROADS", "0") == "1"
FETCH_MISSING_ELEVATION_ONLINE: bool = os.environ.get("LUCIA_FETCH_ELEVATION", "0") == "1"
ARTIFACTS_DIR: str = os.path.join(_MODULE_DIR, "artifacts")
DEFAULT_MODEL_DIR: str = os.path.join(ARTIFACTS_DIR, "models")
DEFAULT_MODEL_PATH: str = os.path.join(DEFAULT_MODEL_DIR, f"lucia_c{DEFAULT_NUM_CHANNELS}.keras")
DEFAULT_ROUTES_DIR: str = os.path.join(ARTIFACTS_DIR, "routes")
DEFAULT_GEOJSON_OUTPUT_PATH: str = os.path.join(DEFAULT_ROUTES_DIR, "lucia_routes.geojson")


@dataclass(frozen=True)
class LuciaModelConfig:
    """Especificación serializable de la arquitectura TensorFlow de LUCIA."""

    grid_size: int = GRID_SIZE
    num_channels: int = DEFAULT_NUM_CHANNELS
    conv_filters: tuple[int, ...] = CONV_FILTERS
    kernel_size: tuple[int, int] = KERNEL_SIZE
    dropout_rate: float = DROPOUT_RATE

    @property
    def input_shape(self) -> tuple[int, int, int]:
        return (self.grid_size, self.grid_size, self.num_channels)

    @property
    def channel_names(self) -> tuple[str, ...]:
        reg = LUCIA_CHANNEL_REGISTRY
        if self.num_channels <= len(reg):
            return reg[: self.num_channels]
        extra = tuple(f"extra_ch_{i}" for i in range(len(reg), self.num_channels))
        return reg + extra
