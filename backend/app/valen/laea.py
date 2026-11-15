"""VALEN — Proyección exacta EPSG:3035 (ETRS89-LAEA Europe) <-> WGS84 sin dependencias C.

Implementación elipsoidal GRS80 (fórmulas OGP/PROJ). Verificada contra los centroides
de `cata_predictions.json` (precisión de 1e-6 grados). Única fuente canónica de la
cuadrícula táctica normalizada **1000 × 1000 m (`ES1K`)** en todo el backend
(VALEN, CATA, LUCIA, JULI y FIRMS Live NRT).
"""

from __future__ import annotations

import math

CELL_SIZE_M: float = 1000.0
CELL_PREFIX: str = "ES1K"
GRID_LEVEL: int = 0
GRID_CRS: str = "EPSG:3035"

_A = 6378137.0
_F = 1.0 / 298.257222101
_E2 = 2.0 * _F - _F * _F
_E = math.sqrt(_E2)
_LON0 = math.radians(10.0)
_LAT0 = math.radians(52.0)
_FE = 4321000.0
_FN = 3210000.0


def _q(sin_phi: float) -> float:
    es = _E * sin_phi
    return (1.0 - _E2) * (
        sin_phi / (1.0 - es * es) - (1.0 / (2.0 * _E)) * math.log((1.0 - es) / (1.0 + es))
    )


_QP = _q(1.0)
_BETA0 = math.asin(_q(math.sin(_LAT0)) / _QP)
_RQ = _A * math.sqrt(0.5 * _QP)
_M0 = math.cos(_LAT0) / math.sqrt(1.0 - _E2 * math.sin(_LAT0) ** 2)
_D = _A * _M0 / (_RQ * math.cos(_BETA0))


def epsg3035_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """EPSG:3035 `(x, y)` metros -> WGS84 `(lon, lat)` grados (6 decimales)."""
    dx = (float(x) - _FE) / _D
    dy = (float(y) - _FN) * _D
    rho = math.hypot(dx, dy)
    if rho == 0.0:
        return round(math.degrees(_LON0), 6), round(math.degrees(_LAT0), 6)
    ce = 2.0 * math.asin(min(1.0, rho / (2.0 * _RQ)))
    sin_ce, cos_ce = math.sin(ce), math.cos(ce)
    q = _QP * (cos_ce * math.sin(_BETA0) + (dy * sin_ce * math.cos(_BETA0)) / rho)
    lon = _LON0 + math.atan2(
        dx * sin_ce, rho * math.cos(_BETA0) * cos_ce - dy * math.sin(_BETA0) * sin_ce
    )
    phi = math.asin(max(-1.0, min(1.0, q / 2.0)))
    for _ in range(6):
        sin_p = math.sin(phi)
        es = _E * sin_p
        phi += (((1.0 - es * es) ** 2) / (2.0 * math.cos(phi))) * (
            q / (1.0 - _E2)
            - sin_p / (1.0 - es * es)
            + (1.0 / (2.0 * _E)) * math.log((1.0 - es) / (1.0 + es))
        )
    return round(math.degrees(lon), 6), round(math.degrees(phi), 6)


def lonlat_to_epsg3035(lon_deg: float, lat_deg: float) -> tuple[float, float]:
    """WGS84 `(lon, lat)` grados -> EPSG:3035 `(x, y)` metros."""
    lon, lat = math.radians(float(lon_deg)), math.radians(float(lat_deg))
    beta = math.asin(max(-1.0, min(1.0, _q(math.sin(lat)) / _QP)))
    dlon = lon - _LON0
    denom = (
        1.0 + math.sin(_BETA0) * math.sin(beta) + math.cos(_BETA0) * math.cos(beta) * math.cos(dlon)
    )
    b = _RQ * math.sqrt(2.0 / max(1e-12, denom))
    x = _FE + (b * _D) * (math.cos(beta) * math.sin(dlon))
    y = _FN + (b / _D) * (
        math.cos(_BETA0) * math.sin(beta) - math.sin(_BETA0) * math.cos(beta) * math.cos(dlon)
    )
    return x, y


def format_cell_id(iy: int, ix: int) -> str:
    """Formatea índices `(iy, ix)` al cuadrante 1000×1000m `ES1K:L0:Y{iy:05d}:X{ix:05d}`."""
    return f"{CELL_PREFIX}:L{GRID_LEVEL}:Y{int(iy):05d}:X{int(ix):05d}"


def parse_cell_id(cell_id: str) -> tuple[int, int]:
    """`ES1K:L0:Y01756:X02856` -> `(1756, 2856)`."""
    parts = str(cell_id).strip().split(":")
    if (
        len(parts) != 4
        or parts[0] != CELL_PREFIX
        or not parts[1].startswith("L")
        or not parts[2].startswith("Y")
        or not parts[3].startswith("X")
    ):
        raise ValueError(
            f"cell_id inválido: {cell_id!r} "
            f"(esperado cuadrante 1000x1000m '{CELL_PREFIX}:L0:Y00000:X00000')"
        )
    return int(parts[2][1:]), int(parts[3][1:])


def lonlat_to_cell_iy_ix(
    lon_deg: float, lat_deg: float, cell_size_m: float = CELL_SIZE_M
) -> tuple[int, int]:
    """WGS84 `(lon, lat)` -> índice `(iy, ix)` del cuadrante `ES1K` (1000×1000 m)."""
    x_m, y_m = lonlat_to_epsg3035(lon_deg, lat_deg)
    ix = int(math.floor(x_m / float(cell_size_m)))
    iy = int(math.floor(y_m / float(cell_size_m)))
    return iy, ix


def cell_centroid_lonlat(
    iy: float, ix: float, cell_size_m: float = CELL_SIZE_M
) -> tuple[float, float]:
    """Índice `(iy, ix)` de cuadrante `ES1K` -> centroide WGS84 `(lon, lat)`."""
    return epsg3035_to_lonlat(
        (float(ix) + 0.5) * float(cell_size_m),
        (float(iy) + 0.5) * float(cell_size_m),
    )


def lonlat_to_cell_id(lon_deg: float, lat_deg: float) -> str:
    """WGS84 `(lon, lat)` -> identificador canónico de cuadrante `ES1K:L0:Y...:X...`."""
    iy, ix = lonlat_to_cell_iy_ix(lon_deg, lat_deg)
    return format_cell_id(iy, ix)


def cell_block_bbox_lonlat(
    origin_iy: int, origin_ix: int, height: int, width: int, cell_size_m: float = CELL_SIZE_M
) -> tuple[float, float, float, float]:
    """BBox WGS84 `(south, west, north, east)` que envuelve un bloque de celdas ES1K."""
    x0, y0 = origin_ix * cell_size_m, origin_iy * cell_size_m
    x1, y1 = (origin_ix + width) * cell_size_m, (origin_iy + height) * cell_size_m
    corners = [epsg3035_to_lonlat(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    return min(lats), min(lons), max(lats), max(lons)
