"""Sistema de coordenadas duales de JULI: Cuadrante 1000x1000m (ES1K) + Subcoordenadas de precisión + WGS84.

Permite localizar a cada operario de forma inequívoca con:
  1. Su cuadrante táctico 1000x1000m (`quadrant_id`: `ES1K:L0:Y{iy}:X{ix}`), 100% compatible
     con la rejilla de VALEN, CATA y LUCIA (`EPSG:3035`).
  2. Sus subcoordenadas exactas dentro de ese cuadrante:
     - Métricas (`offset_x_m`, `offset_y_m` en `[0, 1000)` m desde la esquina SW del cuadrante)
     - Normalizadas (`sub_x_norm`, `sub_y_norm` en `[0, 1)`)
     - Subrejilla táctica 100m (`sub_100m_rc` = `[0..9, 0..9]`) y subrejilla fina 10m (`sub_10m_rc` = `[0..99, 0..99]`)
     - Identificador único de subcuadrante 10m (`sub_cell_id`: `ES1K:L0:Y...:X...:S{yy}_{xx}`)
  3. Coordenadas absolutas precisas en WGS84 (`lon`, `lat`) y proyectadas (`epsg3035_x_m`, `epsg3035_y_m`).
"""

from __future__ import annotations

import math
from typing import Any

try:
    from app.valen.laea import (
        CELL_PREFIX,
        CELL_SIZE_M,
        GRID_CRS,
        GRID_LEVEL,
        epsg3035_to_lonlat,
        lonlat_to_epsg3035,
    )
except ImportError:
    CELL_SIZE_M: float = 1000.0
    CELL_PREFIX: str = "ES1K"
    GRID_LEVEL: int = 0
    GRID_CRS: str = "EPSG:3035"
    # Fallback elipsoidal GRS80 idéntico a `app.valen.laea` para ejecución standalone en `juli/`
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
        lon, lat = math.radians(float(lon_deg)), math.radians(float(lat_deg))
        beta = math.asin(max(-1.0, min(1.0, _q(math.sin(lat)) / _QP)))
        dlon = lon - _LON0
        denom = 1.0 + math.sin(_BETA0) * math.sin(beta) + math.cos(_BETA0) * math.cos(beta) * math.cos(dlon)
        b = _RQ * math.sqrt(2.0 / max(1e-12, denom))
        x = _FE + (b * _D) * (math.cos(beta) * math.sin(dlon))
        y = _FN + (b / _D) * (
            math.cos(_BETA0) * math.sin(beta) - math.sin(_BETA0) * math.cos(beta) * math.cos(dlon)
        )
        return x, y


def parse_quadrant_id(quadrant_id: str) -> tuple[int, int]:
    """Parsea `ES1K:L0:Y02209:X02996` -> `(iy=2209, ix=2996)`."""
    parts = str(quadrant_id).strip().split(":")
    if (
        len(parts) != 4
        or parts[0] != CELL_PREFIX
        or parts[1] != f"L{GRID_LEVEL}"
        or not parts[2].startswith("Y")
        or not parts[3].startswith("X")
    ):
        raise ValueError(
            f"Formato de cuadrante inválido: '{quadrant_id}' "
            f"(esperado '{CELL_PREFIX}:L{GRID_LEVEL}:Y00000:X00000')"
        )
    return int(parts[2][1:]), int(parts[3][1:])


def format_quadrant_id(iy: int, ix: int) -> str:
    """Formatea índices globales `(iy, ix)` -> `ES1K:L0:Y{iy:05d}:X{ix:05d}`."""
    return f"{CELL_PREFIX}:L{GRID_LEVEL}:Y{int(iy):05d}:X{int(ix):05d}"


def lonlat_to_quadrant_subcoords(
    lon: float,
    lat: float,
    cell_size_m: float = CELL_SIZE_M,
) -> dict[str, Any]:
    """Convierte `(lon, lat)` WGS84 en cuadrante 1000x1000m + subcoordenadas locales + métricas EPSG:3035."""
    x_m, y_m = lonlat_to_epsg3035(lon, lat)
    ix = int(math.floor(x_m / cell_size_m))
    iy = int(math.floor(y_m / cell_size_m))
    quadrant_id = format_quadrant_id(iy, ix)

    offset_x_m = max(0.0, min(cell_size_m - 0.01, x_m - ix * cell_size_m))
    offset_y_m = max(0.0, min(cell_size_m - 0.01, y_m - iy * cell_size_m))

    sub_x_norm = round(offset_x_m / cell_size_m, 4)
    sub_y_norm = round(offset_y_m / cell_size_m, 4)

    sub_100_col = min(9, int(offset_x_m // 100.0))
    sub_100_row = min(9, int(offset_y_m // 100.0))
    sub_10_col = min(99, int(offset_x_m // 10.0))
    sub_10_row = min(99, int(offset_y_m // 10.0))

    return {
        "quadrant_id": quadrant_id,
        "quadrant_iy": iy,
        "quadrant_ix": ix,
        "quadrant_size_m": int(cell_size_m),
        "offset_x_m": round(offset_x_m, 2),
        "offset_y_m": round(offset_y_m, 2),
        "sub_x_norm": sub_x_norm,
        "sub_y_norm": sub_y_norm,
        "sub_100m_rc": [sub_100_row, sub_100_col],
        "sub_10m_rc": [sub_10_row, sub_10_col],
        "sub_cell_id": f"{quadrant_id}:S{sub_10_row:02d}_{sub_10_col:02d}",
        "epsg3035_x_m": round(x_m, 2),
        "epsg3035_y_m": round(y_m, 2),
        "lon": round(float(lon), 6),
        "lat": round(float(lat), 6),
    }


def quadrant_subcoords_to_lonlat(
    quadrant_id: str,
    offset_x_m: float | None = None,
    offset_y_m: float | None = None,
    sub_x_norm: float | None = None,
    sub_y_norm: float | None = None,
    cell_size_m: float = CELL_SIZE_M,
) -> tuple[float, float]:
    """Convierte `(quadrant_id + subcoordenadas)` a coordenadas absolutas precisas `(lon, lat)` WGS84."""
    iy, ix = parse_quadrant_id(quadrant_id)
    if offset_x_m is None:
        offset_x_m = (float(sub_x_norm) * cell_size_m) if sub_x_norm is not None else (0.5 * cell_size_m)
    if offset_y_m is None:
        offset_y_m = (float(sub_y_norm) * cell_size_m) if sub_y_norm is not None else (0.5 * cell_size_m)

    ox = max(0.0, min(cell_size_m - 0.01, float(offset_x_m)))
    oy = max(0.0, min(cell_size_m - 0.01, float(offset_y_m)))
    x_m = ix * cell_size_m + ox
    y_m = iy * cell_size_m + oy
    return epsg3035_to_lonlat(x_m, y_m)
