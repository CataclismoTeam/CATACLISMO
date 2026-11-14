"""VALEN — Algoritmo de ingesta, enriquecimiento multi-API y validación inteligente de datos.

Pilares de enriquecimiento de VALEN (`backend/app/valen/`):
  1. `phase1_projection.py` + `phase2_cell_day.py`: Proyección EPSG:3035 (`ES1K`) y agregación `cell_day`.
  2. `meteomatics_client.py`: FWI, viento, humedad y temperatura (Meteomatics API).
  3. `rainfall_client.py`: Días sin lluvia, racha seca y precipitación acumulada (AEMET + ERA5).
  4. `vegetation_client.py`: Inflamabilidad combinada ESA WorldCover 10m + MITECO IFN3.
  5. `roads_client.py`: Red viaria de carreteras, pistas forestales y caminos (OpenStreetMap Overpass API).
  6. `scoring_client.py`: Validación inteligente multi-criterio (`ACEPTA` / `REVISA` / `RECHAZA`).
"""

from .laea import (
    CELL_PREFIX,
    CELL_SIZE_M,
    GRID_LEVEL,
    cell_block_bbox_lonlat,
    epsg3035_to_lonlat,
    format_cell_id,
    lonlat_to_epsg3035,
    parse_cell_id,
)
from .roads_client import (
    HIGHWAY_CLASSES,
    RoadsCache,
    RoadsClient,
    load_cell_roads,
    save_cell_roads,
)

ALGORITHM_NAME: str = "valen"

__all__ = [
    "ALGORITHM_NAME",
    "CELL_PREFIX",
    "CELL_SIZE_M",
    "GRID_LEVEL",
    "HIGHWAY_CLASSES",
    "RoadsCache",
    "RoadsClient",
    "cell_block_bbox_lonlat",
    "epsg3035_to_lonlat",
    "format_cell_id",
    "load_cell_roads",
    "lonlat_to_epsg3035",
    "parse_cell_id",
    "save_cell_roads",
]
