"""LUCIA — Algoritmo de evacuación segura hacia zonas libres de peligro.

Tercer eslabón de la pipeline **VALEN -> CATA -> LUCIA**:
  - Consume las predicciones de **CATA** (`cata_predictions.json`), que a su vez
    integran los datos validados y enriquecidos por **VALEN** (`cell_day`, `meteo`,
    `rainfall`, `vegetation`, `valen_score`).
  - Distingue explícitamente:
      * Zonas **quemándose activamente o de ignición inminente** (`BURNING_ACTIVE`: `'B'` / `'P'`).
      * Zonas **ya quemadas** (`ALREADY_BURNED`: `'F'`).
      * Zonas **sin quemar** (`SAFE`: `'.'`) filtradas con un **threshold seguro al fuego**
        (`SAFE_FIRE_THRESHOLD`).
  - Evalúa un modelo convolucional modular en **TensorFlow/Keras** (`lucia_c13.keras`)
    combinado con búsqueda **A* espacio-temporal** para calcular la ruta más corta y
    segura hacia una **zona libre de peligro** (`SAFE_HAVEN`) tanto para **personas**
    como para **animales**, exportando el resultado en formato **GeoJSON (WGS84)**.
"""

from .config import (
    ALGORITHM_NAME,
    DEFAULT_CATA_PREDICTIONS_PATH,
    DEFAULT_GEOJSON_OUTPUT_PATH,
    DEFAULT_MODEL_PATH,
    DEFAULT_NUM_CHANNELS,
    FIRE_ZONE_ALREADY_BURNED,
    FIRE_ZONE_BURNING_ACTIVE,
    FIRE_ZONE_SAFE_UNBURNED,
    FIRE_ZONE_THRESHOLD_BUFFER,
    LUCIA_CHANNEL_REGISTRY,
    MIN_SAFE_DISTANCE_CELLS,
    PIPELINE_CHAIN,
    SAFE_FIRE_THRESHOLD,
    SAFE_HAVEN_MAX_PROB,
    SOURCE_PREDICTION_ALGORITHM,
    SOURCE_VALIDATION_ALGORITHM,
    LuciaModelConfig,
)
from .model import (
    build_lucia_model,
    create_lucia_model,
    expand_lucia_channels,
    extract_lucia_features_from_zone,
    load_lucia_model,
    lucia_predict_fields,
)
from .router import (
    build_zone_geojson_features,
    cell_iy_ix_to_lonlat,
    cell_iy_ix_to_polygon_lonlat,
    classify_zone_fire_safety,
    compute_Interactive_route_from_lonlat,
    find_safe_evacuation_route,
    generate_lucia_geojson_from_cata,
    identify_safe_havens,
    load_elevation_index,
    load_roads_index,
    load_zone_elevation_grids,
    load_zone_road_grids,
    lonlat_to_cell_iy_ix,
    resolve_zone_meeting_points,
    select_threatened_origins,
)

__all__ = [
    "ALGORITHM_NAME",
    "SOURCE_PREDICTION_ALGORITHM",
    "SOURCE_VALIDATION_ALGORITHM",
    "PIPELINE_CHAIN",
    "LUCIA_CHANNEL_REGISTRY",
    "DEFAULT_NUM_CHANNELS",
    "SAFE_FIRE_THRESHOLD",
    "SAFE_HAVEN_MAX_PROB",
    "MIN_SAFE_DISTANCE_CELLS",
    "FIRE_ZONE_SAFE_UNBURNED",
    "FIRE_ZONE_THRESHOLD_BUFFER",
    "FIRE_ZONE_ALREADY_BURNED",
    "FIRE_ZONE_BURNING_ACTIVE",
    "DEFAULT_CATA_PREDICTIONS_PATH",
    "DEFAULT_MODEL_PATH",
    "DEFAULT_GEOJSON_OUTPUT_PATH",
    "LuciaModelConfig",
    "build_lucia_model",
    "create_lucia_model",
    "load_lucia_model",
    "expand_lucia_channels",
    "extract_lucia_features_from_zone",
    "lucia_predict_fields",
    "cell_iy_ix_to_lonlat",
    "cell_iy_ix_to_polygon_lonlat",
    "lonlat_to_cell_iy_ix",
    "classify_zone_fire_safety",
    "identify_safe_havens",
    "resolve_zone_meeting_points",
    "load_roads_index",
    "load_zone_road_grids",
    "load_elevation_index",
    "load_zone_elevation_grids",
    "select_threatened_origins",
    "find_safe_evacuation_route",
    "build_zone_geojson_features",
    "generate_lucia_geojson_from_cata",
    "compute_Interactive_route_from_lonlat",
]
