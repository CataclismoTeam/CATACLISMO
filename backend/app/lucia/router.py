"""Algoritmo LUCIA — Motor de enrutamiento seguro A* espacio-temporal guiado por TensorFlow
y exportador GeoJSON (WGS84 / RFC 7946) para integración directa en Frontend (CesiumJS / deck.gl).

Integra la pipeline completa:
  VALEN (validación + enriquecimiento) -> CATA (predicción ConvLSTM) -> LUCIA (evacuación segura)

Reglas de seguridad frente al fuego aplicadas por LUCIA:
  1. **Zonas que se están quemando (`BURNING_ACTIVE` — estados `3='B'` y `1='P'`)**:
     Bloqueo estricto intransitable (`passable = False`).
  2. **Zonas ya quemadas (`ALREADY_BURNED` — estado `2='F'`)**:
     Bloqueadas por defecto (`allow_already_burned=False`) por brasas, humo tóxico y caída
     de árboles. Si un evacuado nace completamente rodeado, sólo en modo de rescate de
     último recurso (`emergency_burned_fallback=True`) se permite salir cruzando el mínimo
     número de celdas ya quemadas enfriadas, jamás entrando en fuego activo (`B`/`P`).
  3. **Zonas sin quemar (`SAFE` — estado `0='.'`) con Threshold Seguro al Fuego (`safe_fire_threshold`)**:
     - Si `fire_probability_t1 >= safe_fire_threshold`: clasificada como `THRESHOLD_BUFFER_UNSAFE`
       y bloqueada para garantizar un colchón de seguridad frente al avance del fuego.
     - Si `fire_probability_t1 < safe_fire_threshold`: clasificada como `SAFE_UNBURNED` (transitable).
  4. **Zona libre de peligro (`SAFE_HAVEN` / destino de evacuación)**:
     Celda `SAFE_UNBURNED` con `fire_probability_t1 <= safe_haven_max_prob`, alejada al menos
     `min_safe_distance_cells` del frente de fuego/quemado y con alto `safe_haven_score` neuronal.
"""

from __future__ import annotations

import heapq
import json
import logging
import math
import os
import time
from collections.abc import Sequence
from typing import Any, Literal

import keras
import numpy as np

from . import config
from .model import (
    compute_analytic_target_fields,
    compute_distance_to_hazard,
    extract_lucia_features_from_zone,
    load_lucia_model,
    lucia_predict_fields,
)

logger = logging.getLogger(__name__)

EvacuationProfile = Literal["human", "animal"]

# ===========================================================================
# 1. Georreferenciación exacta EPSG:3035 (ES1K) <-> WGS84 (`[lon, lat]`)
#    Reutiliza la proyección elipsoidal GRS80 de VALEN (`app/valen/laea.py`)
# ===========================================================================
try:
    from ..valen.elevation_client import (
        ElevationClient,
        compute_slope_cost_multiplier,
        load_cell_elevation,
    )
    from ..valen.laea import epsg3035_to_lonlat, lonlat_to_epsg3035
    from ..valen.roads_client import RoadsClient, load_cell_roads
except ImportError:  # ejecución fuera del paquete `app`
    from app.valen.elevation_client import (
        ElevationClient,
        compute_slope_cost_multiplier,
        load_cell_elevation,
    )
    from app.valen.laea import epsg3035_to_lonlat, lonlat_to_epsg3035
    from app.valen.roads_client import RoadsClient, load_cell_roads


def cell_iy_ix_to_lonlat(
    iy: float,
    ix: float,
    cell_size_m: float = config.CELL_SIZE_M,
) -> tuple[float, float]:
    """Convierte índices `(iy, ix)` de la rejilla `ES1K` al centroide WGS84 `(lon, lat)`."""
    x_3035 = (float(ix) + 0.5) * cell_size_m
    y_3035 = (float(iy) + 0.5) * cell_size_m
    return epsg3035_to_lonlat(x_3035, y_3035)


def cell_iy_ix_to_polygon_lonlat(
    iy: int,
    ix: int,
    cell_size_m: float = config.CELL_SIZE_M,
) -> list[list[float]]:
    """Devuelve el anillo exterior GeoJSON (`[[lon, lat], ...]`) del cuadrado 1km×1km `(iy, ix)`."""
    x0 = float(ix) * cell_size_m
    y0 = float(iy) * cell_size_m
    x1 = x0 + cell_size_m
    y1 = y0 + cell_size_m
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    ring: list[list[float]] = []
    for x, y in corners:
        lon, lat = epsg3035_to_lonlat(x, y)
        ring.append([lon, lat])
    return ring


def lonlat_to_cell_iy_ix(
    lon: float,
    lat: float,
    cell_size_m: float = config.CELL_SIZE_M,
) -> tuple[int, int]:
    """Convierte `(lon, lat)` WGS84 al índice `(iy, ix)` de la celda `ES1K` correspondiente."""
    x_3035, y_3035 = lonlat_to_epsg3035(float(lon), float(lat))
    ix = int(math.floor(x_3035 / cell_size_m))
    iy = int(math.floor(y_3035 / cell_size_m))
    return iy, ix


def format_cell_id(iy: int, ix: int) -> str:
    return f"{config.CELL_PREFIX}:L{config.GRID_LEVEL}:Y{iy:05d}:X{ix:05d}"


# ===========================================================================
# 1b. Red viaria OSM de VALEN (carreteras, pistas y senderos) por zona
# ===========================================================================
def load_roads_index(
    roads_path: str = config.DEFAULT_VALEN_ROADS_PATH,
) -> dict[str, dict[str, Any]]:
    """Carga `cell_roads.json` de VALEN como índice `{cell_id: registro}` (vacío si no existe)."""
    try:
        return load_cell_roads(roads_path)
    except (OSError, ValueError) as exc:
        logger.warning("No se pudo leer la red viaria de VALEN (%s): %s", roads_path, exc)
        return {}


def load_zone_road_grids(
    zone: dict,
    roads_index: dict[str, dict[str, Any]] | None,
    fetch_missing_online: bool = config.FETCH_MISSING_ROADS_ONLINE,
) -> dict[str, Any]:
    """Construye las rejillas viarias `(H, W)` de una zona de CATA a partir de VALEN/OSM.

    Devuelve:
      - `road_access`: `road_access_score` [0, 1] (canal 12 del modelo TF).
      - `human_road_factor` / `animal_road_factor`: multiplicadores del coste de paso del A*.
      - `best_highway_class`: matriz de objetos con la mejor vía OSM de cada celda (o None).
      - `coverage`: fracción de celdas de la zona con dato OSM válido (`osm_status == "ok"`).
    """
    y0 = int(zone.get("origin_iy", 0))
    x0 = int(zone.get("origin_ix", 0))
    h, w = (int(v) for v in zone.get("grid_shape", np.asarray(zone["state_matrix"]).shape))

    index = roads_index if roads_index is not None else {}
    probe = [format_cell_id(y0 + r, x0 + c) for r in (0, h - 1) for c in (0, w - 1)]
    if fetch_missing_online and not all(cid in index for cid in probe):
        index = {**index, **RoadsClient().cells_for_block(y0, x0, h, w)}

    access = np.zeros((h, w), dtype=np.float32)
    human_f = np.ones((h, w), dtype=np.float32)
    animal_f = np.ones((h, w), dtype=np.float32)
    best = np.full((h, w), None, dtype=object)
    ok_cells = 0
    for r in range(h):
        for c in range(w):
            rec = index.get(format_cell_id(y0 + r, x0 + c))
            if not rec or rec.get("osm_status") != "ok":
                continue
            ok_cells += 1
            access[r, c] = float(rec.get("road_access_score", 0.0))
            human_f[r, c] = float(rec.get("human_speed_factor", 1.0))
            animal_f[r, c] = float(rec.get("animal_speed_factor", 1.0))
            best[r, c] = rec.get("best_highway_class")

    return {
        "road_access": access,
        "human_road_factor": human_f,
        "animal_road_factor": animal_f,
        "best_highway_class": best,
        "coverage": ok_cells / float(h * w),
    }


# ===========================================================================
# 1c. Topografía y Elevación (Open-Elevation API de VALEN) por zona
# ===========================================================================
def load_elevation_index(
    elevation_path: str = config.DEFAULT_VALEN_ELEVATION_PATH,
) -> dict[str, dict[str, Any]]:
    """Carga `cell_elevation.json` de VALEN como índice `{cell_id: registro}`."""
    try:
        return load_cell_elevation(elevation_path)
    except (OSError, ValueError) as exc:
        logger.warning("No se pudo leer la elevación de VALEN (%s): %s", elevation_path, exc)
        return {}


def load_zone_elevation_grids(
    zone: dict,
    elevation_index: dict[str, dict[str, Any]] | None,
    fetch_missing_online: bool = config.FETCH_MISSING_ELEVATION_ONLINE,
) -> dict[str, Any]:
    """Construye las rejillas de altitud y pendiente `(H, W)` de una zona desde VALEN/Open-Elevation.

    Devuelve:
      - `elevation_m`: altitud sobre el nivel del mar (metros) `(H, W)`.
      - `elevation_norm`: altitud relativa normalizada en `[0, 1]` dentro de la zona (canal 13 TF).
      - `slope_pct`: pendiente media de cada celda en porcentaje `(H, W)`.
      - `slope_steepness`: pendiente normalizada en `[0, 1]` (`slope_pct / 35.0`, canal 14 TF).
      - `elevation_source`: fuente predominante (`"open_elevation_api"` o `"open_elevation_fallback_dem"`).
    """
    y0 = int(zone.get("origin_iy", 0))
    x0 = int(zone.get("origin_ix", 0))
    h, w = (int(v) for v in zone.get("grid_shape", np.asarray(zone["state_matrix"]).shape))

    index = elevation_index if elevation_index is not None else {}
    probe = [format_cell_id(y0 + r, x0 + c) for r in (0, h - 1) for c in (0, w - 1)]
    if not all(cid in index for cid in probe):
        block_cells = ElevationClient().cells_for_block(
            y0, x0, h, w, use_cache=True, allow_online=fetch_missing_online
        )
        index = {**index, **block_cells}

    elev_m = np.zeros((h, w), dtype=np.float32)
    slope_pct = np.zeros((h, w), dtype=np.float32)
    ok_cells = 0
    api_cells = 0
    for r in range(h):
        for c in range(w):
            rec = index.get(format_cell_id(y0 + r, x0 + c))
            if not rec:
                continue
            ok_cells += 1
            elev_m[r, c] = float(rec.get("elevation_m", 0.0))
            slope_pct[r, c] = float(rec.get("slope_pct", 0.0))
            if rec.get("elevation_source") == "open_elevation_api":
                api_cells += 1

    e_min = float(elev_m.min()) if elev_m.size else 0.0
    e_max = float(elev_m.max()) if elev_m.size else 1.0
    span = max(10.0, e_max - e_min)
    elev_norm = np.clip((elev_m - e_min) / span, 0.0, 1.0).astype(np.float32)
    slope_steepness = np.clip(slope_pct / 35.0, 0.0, 1.0).astype(np.float32)

    return {
        "elevation_m": elev_m,
        "elevation_norm": elev_norm,
        "slope_pct": slope_pct,
        "slope_steepness": slope_steepness,
        "min_elevation_m": round(e_min, 1),
        "max_elevation_m": round(e_max, 1),
        "coverage": round(ok_cells / float(max(1, h * w)), 3),
        "open_elevation_api_ratio": round(api_cells / float(max(1, h * w)), 3),
    }


# ===========================================================================
# 2. Clasificación térmica de celdas (Quemadas, Quemándose, Sin Quemar + Threshold)
# ===========================================================================
def classify_zone_fire_safety(
    zone: dict,
    safe_fire_threshold: float = config.SAFE_FIRE_THRESHOLD,
) -> dict[str, np.ndarray]:
    """Clasifica cada celda `(r, c)` de una zona de CATA en las 4 categorías térmicas de LUCIA:

      - `SAFE_UNBURNED` (código 0): Sin quemar (`state == 0`) y `prob_t1 < safe_fire_threshold`.
      - `THRESHOLD_BUFFER_UNSAFE` (código 1): Sin quemar (`state == 0`) pero `prob_t1 >= safe_fire_threshold`.
      - `ALREADY_BURNED` (código 2): Ya quemada (`state == 2 = 'F'`).
      - `BURNING_ACTIVE` (código 3): Quemándose ahora o predicha en llamas (`state == 3 = 'B'` o `state == 1 = 'P'`).
    """
    state_2d = np.asarray(zone["state_matrix"], dtype=np.int8)
    probs_2d = np.asarray(zone["fire_probability_grid"], dtype=np.float32)

    already_burned_mask = state_2d == config.QUADRANT_STATE_BURNED_REAL
    burning_active_mask = (state_2d == config.QUADRANT_STATE_PERSISTENT) | (
        state_2d == config.QUADRANT_STATE_PREDICTED
    )
    threshold_unsafe_mask = (
        (state_2d == config.QUADRANT_STATE_SAFE)
        & (~already_burned_mask)
        & (~burning_active_mask)
        & (probs_2d >= safe_fire_threshold)
    )
    safe_unburned_mask = (
        (state_2d == config.QUADRANT_STATE_SAFE) & (probs_2d < safe_fire_threshold)
    )

    category_code = np.zeros(state_2d.shape, dtype=np.int8)
    category_code[threshold_unsafe_mask] = 1
    category_code[already_burned_mask] = 2
    category_code[burning_active_mask] = 3

    hazard_mask = already_burned_mask | burning_active_mask | threshold_unsafe_mask
    dist_to_hazard = compute_distance_to_hazard(hazard_mask)

    return {
        "category_code": category_code,
        "safe_unburned_mask": safe_unburned_mask,
        "threshold_unsafe_mask": threshold_unsafe_mask,
        "already_burned_mask": already_burned_mask,
        "burning_active_mask": burning_active_mask,
        "dist_to_hazard": dist_to_hazard,
    }


# ===========================================================================
# 3. Selección de orígenes amenazados y zonas libres de peligro (Safe Havens)
# ===========================================================================
def identify_safe_havens(
    safety_info: dict[str, np.ndarray],
    probs_2d: np.ndarray,
    safe_haven_score_2d: np.ndarray,
    min_safe_distance_cells: float = config.MIN_SAFE_DISTANCE_CELLS,
    safe_haven_max_prob: float = config.SAFE_HAVEN_MAX_PROB,
) -> set[tuple[int, int]]:
    """Determina el conjunto de celdas que califican como **Zona Libre de Peligro** (`SAFE_HAVEN`)."""
    safe_mask = safety_info["safe_unburned_mask"]
    dist_to_hazard = safety_info["dist_to_hazard"]

    strict_candidates = (
        safe_mask
        & (probs_2d <= safe_haven_max_prob)
        & (dist_to_hazard >= min_safe_distance_cells)
        & (safe_haven_score_2d >= 0.35)
    )
    pts = np.argwhere(strict_candidates)

    if len(pts) == 0:
        # Relajación progresiva si el incendio ocupa casi toda la ventana
        relaxed = safe_mask & (dist_to_hazard >= max(1.5, min_safe_distance_cells * 0.5))
        pts = np.argwhere(relaxed)
    if len(pts) == 0:
        pts = np.argwhere(safe_mask)

    return {(int(r), int(c)) for r, c in pts}


def select_threatened_origins(
    safety_info: dict[str, np.ndarray],
    probs_2d: np.ndarray,
    max_origins: int = 2,
) -> list[tuple[int, int]]:
    """Selecciona automáticamente puntos de inicio críticos (personas/animales cerca del frente de fuego).

    Busca celdas `SAFE_UNBURNED` situadas a distancia `[1.0, 2.5]` celdas del frente de fuego
    (zonas en peligro inminente que necesitan evacuación inmediata), suficientemente separadas entre sí.
    """
    safe_mask = safety_info["safe_unburned_mask"]
    dist = safety_info["dist_to_hazard"]

    ring_mask = safe_mask & (dist >= 1.0) & (dist <= 2.5)
    candidates = np.argwhere(ring_mask)
    if len(candidates) == 0:
        candidates = np.argwhere(safe_mask)
    if len(candidates) == 0:
        return []

    # Ordenar por mayor cercanía al peligro y mayor probabilidad residual (más urgentes primero)
    scored: list[tuple[float, int, int]] = []
    for r, c in candidates:
        r_i, c_i = int(r), int(c)
        urgency_score = float(probs_2d[r_i, c_i]) * 2.0 - float(dist[r_i, c_i]) * 0.3
        scored.append((urgency_score, r_i, c_i))
    scored.sort(reverse=True)

    selected: list[tuple[int, int]] = []
    for _, r_i, c_i in scored:
        if all(math.hypot(r_i - sr, c_i - sc) >= 6.0 for sr, sc in selected):
            selected.append((r_i, c_i))
            if len(selected) >= max_origins:
                break

    return selected


def resolve_zone_meeting_points(
    zone: dict,
    safety_info: dict[str, np.ndarray],
    probs_2d: np.ndarray,
    safe_haven_score_2d: np.ndarray,
    road_grids: dict[str, Any] | None = None,
    elevation_grids: dict[str, Any] | None = None,
    custom_meeting_points: Sequence[dict[str, Any]] | None = None,
    max_auto_meeting_points: int = config.DEFAULT_MEETING_POINTS_PER_ZONE,
) -> list[dict[str, Any]]:
    """Resuelve y valida los **Puntos de Encuentro (`meeting_point`)** explícitos de una zona.

    1. Si el usuario o Frontend pasa `custom_meeting_points` (con `lon`/`lat`, `cell_id` o `grid_rc`),
       los proyecta sobre la zona y verifica si cada uno está libre de peligro (`is_safe = True`,
       `status = "SAFE_ACTIVE"`) o comprometido por el fuego/umbral (`status = "COMPROMISED_BY_FIRE"`).
    2. Además (o si no se especificaron puntos personalizados seguros), designa automáticamente
       hasta `max_auto_meeting_points` **Puntos de Encuentro Oficiales** en la zona, priorizando:
         - Celdas seguras y alejadas del frente de fuego (`identify_safe_havens`).
         - Terreno llano según **Open-Elevation** (`slope_pct <= MEETING_POINT_MAX_SLOPE_PCT`).
         - Conexión directa a la red viaria de **OpenStreetMap** (`major`/`secondary`/`local`/`track`).
    """
    zone_id = str(zone["zone_id"])
    y0 = int(zone.get("origin_iy", 0))
    x0 = int(zone.get("origin_ix", 0))
    cell_size_m = float(zone.get("cell_size_m", config.CELL_SIZE_M))
    h, w = probs_2d.shape

    safe_mask = safety_info["safe_unburned_mask"]
    dist_to_hazard = safety_info["dist_to_hazard"]

    elev_2d = (
        np.asarray(elevation_grids["elevation_m"], dtype=np.float32)
        if elevation_grids is not None and "elevation_m" in elevation_grids
        else np.zeros((h, w), dtype=np.float32)
    )
    slope_pct_2d = (
        np.asarray(elevation_grids["slope_pct"], dtype=np.float32)
        if elevation_grids is not None and "slope_pct" in elevation_grids
        else np.zeros((h, w), dtype=np.float32)
    )
    road_access_2d = (
        np.asarray(road_grids["road_access"], dtype=np.float32)
        if road_grids is not None and "road_access" in road_grids
        else np.zeros((h, w), dtype=np.float32)
    )
    best_hw_2d = road_grids.get("best_highway_class") if road_grids is not None else None

    meeting_points: list[dict[str, Any]] = []
    seen_rc: set[tuple[int, int]] = set()

    def _build_mp_entry(
        r: int,
        c: int,
        mp_id: str,
        name: str,
        kind: str,
        is_custom: bool,
        capacity: int = 250,
    ) -> dict[str, Any]:
        iy_m, ix_m = y0 + r, x0 + c
        lon_m, lat_m = cell_iy_ix_to_lonlat(iy_m, ix_m, cell_size_m)
        is_safe = bool(safe_mask[r, c]) and float(probs_2d[r, c]) <= max(
            config.SAFE_FIRE_THRESHOLD, config.SAFE_HAVEN_MAX_PROB
        )
        hw_cls = (
            str(best_hw_2d[r, c])
            if best_hw_2d is not None and best_hw_2d[r, c] is not None
            else None
        )
        return {
            "meeting_point_id": mp_id,
            "name": name,
            "kind": kind,
            "is_custom": is_custom,
            "is_safe": is_safe,
            "status": "SAFE_ACTIVE" if is_safe else "COMPROMISED_BY_FIRE",
            "zone_id": zone_id,
            "cell_id": format_cell_id(iy_m, ix_m),
            "grid_rc": [int(r), int(c)],
            "lon": lon_m,
            "lat": lat_m,
            "coordinates": [lon_m, lat_m],
            "elevation_m": round(float(elev_2d[r, c]), 1),
            "slope_pct": round(float(slope_pct_2d[r, c]), 2),
            "road_access_score": round(float(road_access_2d[r, c]), 4),
            "has_road_access": bool(road_access_2d[r, c] > 0.0),
            "best_highway_class": hw_cls,
            "fire_zone_category": (
                config.FIRE_ZONE_SAFE_UNBURNED if is_safe else config.FIRE_ZONE_BURNING_ACTIVE
            ),
            "safe_haven_score": round(float(safe_haven_score_2d[r, c]), 4),
            "fire_probability_t1": round(float(probs_2d[r, c]), 4),
            "distance_to_fire_km": round(float(dist_to_hazard[r, c]) * (cell_size_m / 1000.0), 2),
            "capacity": int(capacity),
        }

    # 1. Procesar puntos de encuentro personalizados enviados por el usuario / API
    if custom_meeting_points:
        for idx, raw_mp in enumerate(custom_meeting_points):
            mp_zone = raw_mp.get("zone_id")
            if mp_zone and str(mp_zone) != zone_id:
                continue
            rc_pair: tuple[int, int] | None = None
            if "grid_rc" in raw_mp and raw_mp["grid_rc"] is not None:
                gr, gc = raw_mp["grid_rc"]
                rc_pair = (int(gr), int(gc))
            elif "lon" in raw_mp and "lat" in raw_mp:
                iy_t, ix_t = lonlat_to_cell_iy_ix(
                    float(raw_mp["lon"]), float(raw_mp["lat"]), cell_size_m
                )
                r_t, c_t = iy_t - y0, ix_t - x0
                if 0 <= r_t < h and 0 <= c_t < w:
                    rc_pair = (r_t, c_t)
            if rc_pair is None:
                continue
            r_c, c_c = rc_pair
            if not (0 <= r_c < h and 0 <= c_c < w) or (r_c, c_c) in seen_rc:
                continue
            seen_rc.add((r_c, c_c))
            mp_id = str(raw_mp.get("id") or raw_mp.get("meeting_point_id") or f"{zone_id}_mp_custom_{idx}")
            mp_name = str(raw_mp.get("name") or f"Punto de Encuentro Personalizado #{idx + 1}")
            mp_kind = str(raw_mp.get("kind") or "custom_user_meeting_point")
            mp_cap = int(raw_mp.get("capacity", 300))
            meeting_points.append(
                _build_mp_entry(r_c, c_c, mp_id, mp_name, mp_kind, is_custom=True, capacity=mp_cap)
            )

    # 2. Completar con Puntos de Encuentro Oficiales óptimos (carretera OSM + llano Open-Elevation + lejos del fuego)
    safe_custom_count = sum(1 for mp in meeting_points if mp["is_safe"])
    if safe_custom_count < max_auto_meeting_points:
        candidate_havens = identify_safe_havens(safety_info, probs_2d, safe_haven_score_2d)
        scored_havens: list[tuple[float, int, int]] = []
        for hr, hc in candidate_havens:
            if (hr, hc) in seen_rc:
                continue
            flat_bonus = max(0.0, 1.0 - float(slope_pct_2d[hr, hc]) / 20.0)
            road_bonus = float(road_access_2d[hr, hc])
            dist_bonus = min(1.0, float(dist_to_hazard[hr, hc]) / 8.0)
            mp_score = (
                float(safe_haven_score_2d[hr, hc])
                + 0.40 * road_bonus
                + 0.25 * flat_bonus
                + 0.20 * dist_bonus
            )
            scored_havens.append((mp_score, int(hr), int(hc)))
        scored_havens.sort(reverse=True)

        auto_added = 0
        for _, hr, hc in scored_havens:
            if any(math.hypot(hr - sr, hc - sc) < 7.0 for sr, sc in seen_rc):
                continue
            seen_rc.add((hr, hc))
            auto_added += 1
            hw_cls = (
                str(best_hw_2d[hr, hc])
                if best_hw_2d is not None and best_hw_2d[hr, hc] is not None
                else None
            )
            if hw_cls in ("motorway", "trunk", "primary", "secondary", "tertiary"):
                kind = "road_junction_assembly"
                label_prefix = f"Punto de Encuentro Vial ({hw_cls})"
            elif hw_cls is not None:
                kind = "rural_track_assembly"
                label_prefix = f"Punto de Encuentro Forestal ({hw_cls})"
            else:
                kind = "flat_clearing_assembly"
                label_prefix = "Punto de Encuentro Explanada Segura"

            mp_id = f"{zone_id}_mp_{auto_added}"
            mp_name = f"P.E. #{auto_added} — {label_prefix} ({int(round(elev_2d[hr, hc]))} m)"
            meeting_points.append(
                _build_mp_entry(
                    hr, hc, mp_id, mp_name, kind, is_custom=False, capacity=400
                )
            )
            if safe_custom_count + auto_added >= max_auto_meeting_points:
                break

    return meeting_points


# ===========================================================================
# 4. Búsqueda A* espacio-temporal híbrida (TensorFlow + Reglas Físicas + Open-Elevation)
# ===========================================================================
def find_safe_evacuation_route(
    zone: dict,
    tf_fields: dict[str, np.ndarray],
    start_rc: tuple[int, int],
    profile: EvacuationProfile = "human",
    target_havens: set[tuple[int, int]] | None = None,
    safe_fire_threshold: float = config.SAFE_FIRE_THRESHOLD,
    safety_time_margin_hours: float = config.SAFETY_TIME_MARGIN_HOURS,
    allow_already_burned: bool = False,
    emergency_burned_fallback: bool = True,
    road_grids: dict[str, Any] | None = None,
    elevation_grids: dict[str, Any] | None = None,
    meeting_points_by_rc: dict[tuple[int, int], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Encuentra el camino más corto y seguro desde `start_rc` hasta una **zona libre de peligro**.

    Garantiza:
      - No pisar jamás celdas en llamas o predichas (`BURNING_ACTIVE`: `'B'` o `'P'`).
      - No pisar celdas sin quemar que superen el `safe_fire_threshold` (`THRESHOLD_BUFFER_UNSAFE`).
      - No pisar celdas ya quemadas (`ALREADY_BURNED`: `'F'`) salvo que `allow_already_burned=True`
        o que el punto de inicio esté completamente cercado y se active `emergency_burned_fallback`.
      - Cumplir la ventana temporal: `tiempo_llegada_horas + safety_time_margin_hours < estimated_fire_arrival_hours`.
      - Minimizar el funcional híbrido (distancia + coste físico CATA + campo neuronal TensorFlow LUCIA).
      - Aprovechar carreteras, pistas y senderos OSM de VALEN (`road_grids`): el coste de paso de cada
        celda se multiplica por su `human_speed_factor` / `animal_speed_factor` (< 1 en vías rápidas,
        > 1 en autovías valladas para animales). Nunca permite cruzar fuego por ir por carretera.
    """
    probs_2d = np.asarray(zone["fire_probability_grid"], dtype=np.float32)
    arrival_2d = np.asarray(zone["estimated_fire_arrival_hours"], dtype=np.float32)
    base_cost_2d = np.asarray(
        zone["human_traversal_cost_grid"]
        if profile == "human"
        else zone["animal_traversal_cost_grid"],
        dtype=np.float32,
    )
    if road_grids is not None:
        road_factor_2d = np.asarray(
            road_grids["human_road_factor" if profile == "human" else "animal_road_factor"],
            dtype=np.float32,
        )
        best_class_2d = road_grids.get("best_highway_class")
    else:
        road_factor_2d = np.ones_like(base_cost_2d)
        best_class_2d = None

    if elevation_grids is not None and "elevation_m" in elevation_grids:
        elev_2d = np.asarray(elevation_grids["elevation_m"], dtype=np.float32)
    else:
        elev_2d = np.full_like(base_cost_2d, 500.0, dtype=np.float32)

    # Heurística admisible: escalar por el factor viario más rápido y el mínimo factor de pendiente de Tobler (~0.83)
    heuristic_scale = float(min(1.0, road_factor_2d.min())) * 0.82 if road_factor_2d.size else 0.82
    tf_risk_2d = np.asarray(
        tf_fields["human_risk_field"] if profile == "human" else tf_fields["animal_risk_field"],
        dtype=np.float32,
    )
    safe_haven_2d = np.asarray(tf_fields["safe_haven_score"], dtype=np.float32)

    safety_info = classify_zone_fire_safety(zone, safe_fire_threshold=safe_fire_threshold)
    h, w = probs_2d.shape
    sr, sc = int(start_rc[0]), int(start_rc[1])
    if not (0 <= sr < h and 0 <= sc < w):
        return None

    havens = (
        set(target_havens)
        if target_havens
        else identify_safe_havens(safety_info, probs_2d, safe_haven_2d)
    )
    if not havens:
        return None

    speed_kmh = (
        config.HUMAN_BASE_SPEED_KMH if profile == "human" else config.ANIMAL_BASE_SPEED_KMH
    )
    cell_size_m = float(zone.get("cell_size_m", config.CELL_SIZE_M))
    cell_km = cell_size_m / 1000.0

    def _run_astar(permit_burned_escape: bool) -> dict[str, Any] | None:
        burning_mask = safety_info["burning_active_mask"]
        already_burned_mask = safety_info["already_burned_mask"]
        threshold_unsafe_mask = safety_info["threshold_unsafe_mask"]
        dist_to_hazard = safety_info["dist_to_hazard"]

        # Si el propio punto de partida está en llamas activas, no es viable
        if burning_mask[sr, sc]:
            return None

        haven_list = list(havens)

        def heuristic(r: int, c: int) -> float:
            # Distancia Octile mínima hacia el conjunto de Puntos de Encuentro / zonas seguras
            d_min = float("inf")
            for hr, hc in haven_list:
                dr = abs(r - hr)
                dc = abs(c - hc)
                d_oct = min(dr, dc) * 1.41421356 + abs(dr - dc)
                if d_oct < d_min:
                    d_min = d_oct
            return (d_min * cell_km * heuristic_scale) / speed_kmh

        directions = [
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        ]

        # (f_score, g_cost, elapsed_hours, r, c)
        open_heap: list[tuple[float, float, float, int, int]] = [
            (heuristic(sr, sc), 0.0, 0.0, sr, sc)
        ]
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        g_costs: dict[tuple[int, int], float] = {(sr, sc): 0.0}
        arrival_times: dict[tuple[int, int], float] = {(sr, sc): 0.0}

        reached_goal: tuple[int, int] | None = None

        while open_heap:
            f_val, g_val, t_hours, r, c = heapq.heappop(open_heap)
            if g_val > g_costs.get((r, c), float("inf")):
                continue

            if (r, c) in havens and (r, c) != (sr, sc):
                reached_goal = (r, c)
                break

            for dr, dc in directions:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < h and 0 <= nc < w):
                    continue

                # 1. Bloqueo absoluto de celdas que se están quemando o predichas ('B' / 'P')
                if burning_mask[nr, nc]:
                    continue

                # 2. Bloqueo por threshold seguro al fuego en celdas sin quemar
                if threshold_unsafe_mask[nr, nc] and not permit_burned_escape:
                    continue

                # 3. Bloqueo de celdas ya quemadas ('F') salvo modo rescate de emergencia
                is_burned_step = bool(already_burned_mask[nr, nc])
                if is_burned_step and not permit_burned_escape:
                    continue

                step_cells = math.hypot(dr, dc)
                step_dist_m = step_cells * cell_size_m
                step_dist_km = step_cells * cell_km

                # 4. Cambio de elevación direccional Δz (Open-Elevation VALEN) y función de Tobler
                delta_z = float(elev_2d[nr, nc] - elev_2d[r, c])
                slope_mult = compute_slope_cost_multiplier(
                    delta_elev_m=delta_z,
                    horizontal_dist_m=step_dist_m,
                    profile=profile,
                )

                road_mult = float(road_factor_2d[nr, nc])
                terrain_mult = float(base_cost_2d[nr, nc]) * road_mult * slope_mult
                step_hours = (step_dist_km * terrain_mult) / speed_kmh
                next_time_hours = t_hours + step_hours

                # 5. Condición espacio-temporal de supervivencia frente al frente de fuego
                fire_arrival = float(arrival_2d[nr, nc])
                if not is_burned_step and next_time_hours + safety_time_margin_hours >= fire_arrival:
                    continue

                # 6. Coste híbrido: tiempo físico (OSM + Tobler Δz) + riesgo neuronal TF + efecto chimenea cuesta arriba
                neural_risk = float(tf_risk_2d[nr, nc])
                prob_cell = float(probs_2d[nr, nc])
                dist_f = float(dist_to_hazard[nr, nc])
                prox_penalty = 1.2 / max(0.5, dist_f)

                # Penalización por subir cuesta arriba cerca de un frente activo (efecto chimenea convectivo)
                uphill_chimney_penalty = 0.0
                if delta_z > 5.0 and dist_f < 4.5:
                    slope_ratio = delta_z / max(1.0, step_dist_m)
                    uphill_chimney_penalty = min(
                        1.8, (slope_ratio / 0.12) * (1.5 / max(0.75, dist_f))
                    )

                burned_emergency_penalty = 15.0 if is_burned_step else 0.0
                haven_bonus = -0.15 * float(safe_haven_2d[nr, nc])

                step_total_cost = (
                    step_hours
                    * (
                        1.0
                        + 2.2 * neural_risk
                        + 3.0 * prob_cell
                        + 0.45 * prox_penalty
                        + uphill_chimney_penalty
                    )
                    + burned_emergency_penalty
                    + max(0.0, haven_bonus)
                )
                next_g = g_val + step_total_cost

                if next_g < g_costs.get((nr, nc), float("inf")):
                    g_costs[(nr, nc)] = next_g
                    arrival_times[(nr, nc)] = next_time_hours
                    came_from[(nr, nc)] = (r, c)
                    heapq.heappush(
                        open_heap,
                        (next_g + heuristic(nr, nc), next_g, next_time_hours, nr, nc),
                    )

        if reached_goal is None:
            return None

        # Reconstruir el camino óptimo
        path_rc: list[tuple[int, int]] = []
        curr: tuple[int, int] | None = reached_goal
        while curr is not None:
            path_rc.append(curr)
            curr = came_from.get(curr)
        path_rc.reverse()

        # Calcular métricas detalladas de la ruta (OSM + Open-Elevation + Punto de Encuentro)
        total_dist_m = 0.0
        max_prob_along = 0.0
        min_fire_margin_h = float("inf")
        min_dist_to_fire_km = float("inf")
        burned_cells_crossed = 0
        road_cells_used = 0
        highway_classes_used: list[str] = []
        elevation_profile_m: list[float] = []
        total_ascent_m = 0.0
        total_descent_m = 0.0
        max_slope_pct = 0.0

        for idx in range(len(path_rc)):
            pr, pc = path_rc[idx]
            z_cur = round(float(elev_2d[pr, pc]), 1)
            elevation_profile_m.append(z_cur)

            p_val = float(probs_2d[pr, pc])
            if p_val > max_prob_along:
                max_prob_along = p_val
            d_km = float(dist_to_hazard[pr, pc]) * cell_km
            if d_km < min_dist_to_fire_km:
                min_dist_to_fire_km = d_km
            if already_burned_mask[pr, pc]:
                burned_cells_crossed += 1
            if best_class_2d is not None and best_class_2d[pr, pc] is not None:
                road_cells_used += 1
                hw_cls = str(best_class_2d[pr, pc])
                if hw_cls not in highway_classes_used:
                    highway_classes_used.append(hw_cls)

            if idx > 0:
                r0, c0 = path_rc[idx - 1]
                step_d_m = math.hypot(pr - r0, pc - c0) * cell_size_m
                total_dist_m += step_d_m
                dz = float(elev_2d[pr, pc] - elev_2d[r0, c0])
                if dz > 0:
                    total_ascent_m += dz
                else:
                    total_descent_m += abs(dz)
                step_slope_pct = (abs(dz) / max(1.0, step_d_m)) * 100.0
                if step_slope_pct > max_slope_pct:
                    max_slope_pct = step_slope_pct

                t_arr = arrival_times.get((pr, pc), 0.0)
                f_arr = float(arrival_2d[pr, pc])
                if f_arr < 900.0:
                    margin = f_arr - t_arr
                    if margin < min_fire_margin_h:
                        min_fire_margin_h = margin

        total_hours = arrival_times.get(reached_goal, 0.0)
        dest_r, dest_c = reached_goal
        start_elev_m = round(float(elev_2d[sr, sc]), 1)
        end_elev_m = round(float(elev_2d[dest_r, dest_c]), 1)

        mp_meta = (
            meeting_points_by_rc.get((dest_r, dest_c))
            if meeting_points_by_rc is not None
            else None
        )

        return {
            "viable": True,
            "profile": profile,
            "emergency_burned_escape_used": permit_burned_escape and burned_cells_crossed > 0,
            "path_grid_rc": path_rc,
            "steps": len(path_rc) - 1,
            "distance_m": round(total_dist_m, 1),
            "distance_km": round(total_dist_m / 1000.0, 3),
            "estimated_time_hours": round(total_hours, 3),
            "estimated_time_minutes": round(total_hours * 60.0, 1),
            "max_fire_probability_on_route": round(max_prob_along, 4),
            "safe_fire_threshold_applied": safe_fire_threshold,
            "min_distance_to_fire_km": round(min_dist_to_fire_km, 2),
            "min_fire_time_margin_hours": (
                round(min_fire_margin_h, 2) if min_fire_margin_h != float("inf") else None
            ),
            "burned_cells_crossed": burned_cells_crossed,
            "road_cells_used": road_cells_used,
            "road_share_ratio": round(road_cells_used / max(1, len(path_rc)), 3),
            "highway_classes_used": highway_classes_used,
            "start_elevation_m": start_elev_m,
            "end_elevation_m": end_elev_m,
            "net_elevation_change_m": round(end_elev_m - start_elev_m, 1),
            "total_ascent_m": round(total_ascent_m, 1),
            "total_descent_m": round(total_descent_m, 1),
            "max_slope_pct": round(max_slope_pct, 2),
            "elevation_profile_m": elevation_profile_m,
            "target_type": "meeting_point" if mp_meta is not None else "safe_haven",
            "target_meeting_point_id": mp_meta["meeting_point_id"] if mp_meta else None,
            "target_meeting_point_name": mp_meta["name"] if mp_meta else None,
            "target_meeting_point_kind": mp_meta["kind"] if mp_meta else None,
            "target_meeting_point_lonlat": [mp_meta["lon"], mp_meta["lat"]] if mp_meta else None,
            "target_meeting_point_elevation_m": mp_meta["elevation_m"] if mp_meta else end_elev_m,
            "destination_safe_haven_score": round(float(safe_haven_2d[dest_r, dest_c]), 4),
            "destination_fire_probability": round(float(probs_2d[dest_r, dest_c]), 4),
        }

    # Intento 1: Ruta 100% limpia (sin pisar jamás zonas ya quemadas ni zonas > threshold)
    route = _run_astar(permit_burned_escape=allow_already_burned)
    if route is None and emergency_burned_fallback and not allow_already_burned:
        # Intento 2: Sólo si el origen estaba encerrado, permite cruzar borde ya quemado enfriado
        route = _run_astar(permit_burned_escape=True)
    return route


# ===========================================================================
# 5. Exportación a GeoJSON (RFC 7946) para el compañero de Frontend
# ===========================================================================
def build_zone_geojson_features(
    zone: dict,
    active_cells_for_zone: Sequence[dict] | None = None,
    model: keras.Model | None = None,
    profiles: Sequence[EvacuationProfile] = ("human", "animal"),
    custom_origins_rc: Sequence[tuple[int, int]] | None = None,
    custom_meeting_points: Sequence[dict[str, Any]] | None = None,
    safe_fire_threshold: float = config.SAFE_FIRE_THRESHOLD,
    include_fire_polygons: bool = True,
    roads_index: dict[str, dict[str, Any]] | None = None,
    elevation_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Genera todos los `Feature` GeoJSON (rutas, orígenes, puntos de encuentro y celdas de fuego) de una zona."""
    zone_id = str(zone["zone_id"])
    y0 = int(zone.get("origin_iy", 0))
    x0 = int(zone.get("origin_ix", 0))
    cell_size_m = float(zone.get("cell_size_m", config.CELL_SIZE_M))
    ref_date = str(zone.get("reference_date", "t"))
    pred_date = str(zone.get("predicted_date", "t+1"))

    if roads_index is None:
        roads_index = load_roads_index()
    road_grids = load_zone_road_grids(zone, roads_index)

    if elevation_index is None:
        elevation_index = load_elevation_index()
    elevation_grids = load_zone_elevation_grids(zone, elevation_index)
    elev_2d = np.asarray(elevation_grids["elevation_m"], dtype=np.float32)

    features_tensor = extract_lucia_features_from_zone(
        zone,
        active_cells_for_zone=active_cells_for_zone,
        safe_fire_threshold=safe_fire_threshold,
        road_grids=road_grids,
        elevation_grids=elevation_grids,
    )
    if model is not None:
        tf_fields = lucia_predict_fields(model, features_tensor)
    else:
        analytic = compute_analytic_target_fields(features_tensor)
        tf_fields = {
            "human_risk_field": analytic[..., 0],
            "animal_risk_field": analytic[..., 1],
            "safe_haven_score": analytic[..., 2],
        }

    probs_2d = np.asarray(zone["fire_probability_grid"], dtype=np.float32)
    state_2d = np.asarray(zone["state_matrix"], dtype=np.int8)
    safety_info = classify_zone_fire_safety(zone, safe_fire_threshold=safe_fire_threshold)

    # Resolver Puntos de Encuentro explícitos (oficiales automáticos + personalizados del usuario)
    meeting_points = resolve_zone_meeting_points(
        zone=zone,
        safety_info=safety_info,
        probs_2d=probs_2d,
        safe_haven_score_2d=tf_fields["safe_haven_score"],
        road_grids=road_grids,
        elevation_grids=elevation_grids,
        custom_meeting_points=custom_meeting_points,
    )
    meeting_points_by_rc: dict[tuple[int, int], dict[str, Any]] = {
        tuple(mp["grid_rc"]): mp for mp in meeting_points
    }
    safe_mp_targets: set[tuple[int, int]] = {
        tuple(mp["grid_rc"]) for mp in meeting_points if mp.get("is_safe", False)
    }
    havens = (
        safe_mp_targets
        if safe_mp_targets
        else identify_safe_havens(safety_info, probs_2d, tf_fields["safe_haven_score"])
    )

    origins_rc = (
        list(custom_origins_rc)
        if custom_origins_rc
        else select_threatened_origins(safety_info, probs_2d, max_origins=2)
    )

    geojson_features: list[dict[str, Any]] = []
    routes_found = 0
    reached_havens: set[tuple[int, int]] = set()

    # 1. Calcular y exportar rutas de evacuación para cada origen y perfil (human / animal)
    for origin_idx, start_rc in enumerate(origins_rc):
        sr, sc = int(start_rc[0]), int(start_rc[1])
        start_iy, start_ix = y0 + sr, x0 + sc
        start_lon, start_lat = cell_iy_ix_to_lonlat(start_iy, start_ix, cell_size_m)
        start_coords_3d = [start_lon, start_lat, round(float(elev_2d[sr, sc]), 1)]

        # Feature Point: Punto de origen amenazado
        geojson_features.append(
            {
                "type": "Feature",
                "id": f"{zone_id}_origin_{origin_idx}",
                "geometry": {
                    "type": "Point",
                    "coordinates": start_coords_3d,
                },
                "properties": {
                    "feature_type": "evacuation_origin",
                    "zone_id": zone_id,
                    "origin_index": origin_idx,
                    "cell_id": format_cell_id(start_iy, start_ix),
                    "grid_rc": [sr, sc],
                    "elevation_m": round(float(elev_2d[sr, sc]), 1),
                    "fire_zone_category": config.FIRE_ZONE_SAFE_UNBURNED,
                    "fire_probability_t1": round(float(probs_2d[sr, sc]), 4),
                    "distance_to_fire_km": round(
                        float(safety_info["dist_to_hazard"][sr, sc]) * (cell_size_m / 1000.0), 2
                    ),
                    "reference_date": ref_date,
                    "predicted_date": pred_date,
                    "stroke_color": "#f59e0b",
                    "marker_symbol": "warning",
                },
            }
        )

        for profile in profiles:
            route_info = find_safe_evacuation_route(
                zone=zone,
                tf_fields=tf_fields,
                start_rc=(sr, sc),
                profile=profile,
                target_havens=havens,
                safe_fire_threshold=safe_fire_threshold,
                road_grids=road_grids,
                elevation_grids=elevation_grids,
                meeting_points_by_rc=meeting_points_by_rc,
            )
            if not route_info or not route_info.get("viable"):
                continue

            routes_found += 1
            path_rc: list[tuple[int, int]] = route_info["path_grid_rc"]
            dest_r, dest_c = path_rc[-1]
            reached_havens.add((dest_r, dest_c))

            coords_lonlat_3d: list[list[float]] = []
            cell_ids_along: list[str] = []
            for r_step, c_step in path_rc:
                iy_step, ix_step = y0 + r_step, x0 + c_step
                lon_s, lat_s = cell_iy_ix_to_lonlat(iy_step, ix_step, cell_size_m)
                z_s = round(float(elev_2d[r_step, c_step]), 1)
                coords_lonlat_3d.append([lon_s, lat_s, z_s])
                cell_ids_along.append(format_cell_id(iy_step, ix_step))

            color_hex = "#10b981" if profile == "human" else "#38bdf8"
            geojson_features.append(
                {
                    "type": "Feature",
                    "id": f"{zone_id}_route_{origin_idx}_{profile}",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords_lonlat_3d,
                    },
                    "properties": {
                        "feature_type": "evacuation_route",
                        "algorithm": config.ALGORITHM_NAME,
                        "pipeline": list(config.PIPELINE_CHAIN),
                        "zone_id": zone_id,
                        "origin_index": origin_idx,
                        "profile": profile,
                        "profile_label": (
                            "Evacuación Personas"
                            if profile == "human"
                            else "Evacuación Animales / Fauna"
                        ),
                        "start_cell_id": cell_ids_along[0],
                        "end_safe_haven_cell_id": cell_ids_along[-1],
                        "target_type": route_info["target_type"],
                        "target_meeting_point_id": route_info["target_meeting_point_id"],
                        "target_meeting_point_name": route_info["target_meeting_point_name"],
                        "target_meeting_point_kind": route_info["target_meeting_point_kind"],
                        "target_meeting_point_lonlat": route_info["target_meeting_point_lonlat"],
                        "target_meeting_point_elevation_m": route_info[
                            "target_meeting_point_elevation_m"
                        ],
                        "cell_ids": cell_ids_along,
                        "steps": route_info["steps"],
                        "distance_m": route_info["distance_m"],
                        "distance_km": route_info["distance_km"],
                        "estimated_time_minutes": route_info["estimated_time_minutes"],
                        "estimated_time_hours": route_info["estimated_time_hours"],
                        "start_elevation_m": route_info["start_elevation_m"],
                        "end_elevation_m": route_info["end_elevation_m"],
                        "net_elevation_change_m": route_info["net_elevation_change_m"],
                        "total_ascent_m": route_info["total_ascent_m"],
                        "total_descent_m": route_info["total_descent_m"],
                        "max_slope_pct": route_info["max_slope_pct"],
                        "elevation_profile_m": route_info["elevation_profile_m"],
                        "max_fire_probability_on_route": route_info[
                            "max_fire_probability_on_route"
                        ],
                        "safe_fire_threshold": route_info["safe_fire_threshold_applied"],
                        "min_distance_to_fire_km": route_info["min_distance_to_fire_km"],
                        "min_fire_time_margin_hours": route_info["min_fire_time_margin_hours"],
                        "burned_cells_crossed": route_info["burned_cells_crossed"],
                        "road_cells_used": route_info.get("road_cells_used", 0),
                        "road_share_ratio": route_info.get("road_share_ratio", 0.0),
                        "highway_classes_used": route_info.get("highway_classes_used", []),
                        "emergency_burned_escape_used": route_info[
                            "emergency_burned_escape_used"
                        ],
                        "destination_safe_haven_score": route_info[
                            "destination_safe_haven_score"
                        ],
                        "reference_date": ref_date,
                        "predicted_date": pred_date,
                        "stroke_color": color_hex,
                        "stroke_width": 5 if profile == "human" else 4,
                    },
                }
            )

    # 2. Exportar los Puntos de Encuentro (Meeting Points) de la zona como Features explícitas
    for mp in meeting_points:
        hr, hc = int(mp["grid_rc"][0]), int(mp["grid_rc"][1])
        is_reached = (hr, hc) in reached_havens
        geojson_features.append(
            {
                "type": "Feature",
                "id": mp["meeting_point_id"],
                "geometry": {
                    "type": "Point",
                    "coordinates": [mp["lon"], mp["lat"], mp["elevation_m"]],
                },
                "properties": {
                    "feature_type": "meeting_point",
                    "is_safe_haven": bool(mp["is_safe"]),
                    "is_assigned_destination": is_reached,
                    "meeting_point_id": mp["meeting_point_id"],
                    "name": mp["name"],
                    "kind": mp["kind"],
                    "is_custom": mp["is_custom"],
                    "status": mp["status"],
                    "capacity": mp["capacity"],
                    "zone_id": zone_id,
                    "cell_id": mp["cell_id"],
                    "grid_rc": [hr, hc],
                    "elevation_m": mp["elevation_m"],
                    "slope_pct": mp["slope_pct"],
                    "best_highway_class": mp["best_highway_class"],
                    "has_road_access": mp["has_road_access"],
                    "fire_zone_category": mp["fire_zone_category"],
                    "safe_haven_score": mp["safe_haven_score"],
                    "fire_probability_t1": mp["fire_probability_t1"],
                    "distance_to_fire_km": mp["distance_to_fire_km"],
                    "reference_date": ref_date,
                    "predicted_date": pred_date,
                    "fill_color": "#22c55e" if mp["is_safe"] else "#dc2626",
                    "marker_symbol": "meeting-point" if mp["is_safe"] else "danger",
                },
            }
        )

    # 2b. Compatibilidad retroactiva: exportar también `safe_haven` para los destinos alcanzados
    for hr, hc in sorted(reached_havens):
        h_iy, h_ix = y0 + hr, x0 + hc
        h_lon, h_lat = cell_iy_ix_to_lonlat(h_iy, h_ix, cell_size_m)
        h_elev = round(float(elev_2d[hr, hc]), 1)
        mp_match = meeting_points_by_rc.get((hr, hc))
        geojson_features.append(
            {
                "type": "Feature",
                "id": f"{zone_id}_safe_haven_{hr}_{hc}",
                "geometry": {
                    "type": "Point",
                    "coordinates": [h_lon, h_lat, h_elev],
                },
                "properties": {
                    "feature_type": "safe_haven",
                    "meeting_point_id": mp_match["meeting_point_id"] if mp_match else None,
                    "meeting_point_name": mp_match["name"] if mp_match else "Zona Libre de Peligro",
                    "zone_id": zone_id,
                    "cell_id": format_cell_id(h_iy, h_ix),
                    "grid_rc": [hr, hc],
                    "elevation_m": h_elev,
                    "fire_zone_category": config.FIRE_ZONE_SAFE_UNBURNED,
                    "safe_haven_score": round(float(tf_fields["safe_haven_score"][hr, hc]), 4),
                    "fire_probability_t1": round(float(probs_2d[hr, hc]), 4),
                    "distance_to_fire_km": round(
                        float(safety_info["dist_to_hazard"][hr, hc]) * (cell_size_m / 1000.0), 2
                    ),
                    "reference_date": ref_date,
                    "predicted_date": pred_date,
                    "fill_color": "#22c55e",
                    "marker_symbol": "shelter",
                },
            }
        )

    # 3. Exportar polígonos 1km×1km de las zonas quemadas, quemándose y del buffer del threshold
    if include_fire_polygons:
        h, w = state_2d.shape
        cat_code = safety_info["category_code"]
        for r in range(h):
            for c in range(w):
                code = int(cat_code[r, c])
                if code == 0:
                    continue  # Omitimos las celdas normales sin quemar para que el GeoJSON sea ligero

                c_iy, c_ix = y0 + r, x0 + c
                poly_coords = cell_iy_ix_to_polygon_lonlat(c_iy, c_ix, cell_size_m)
                st_cata = int(state_2d[r, c])

                if code == 3:
                    cat_name = config.FIRE_ZONE_BURNING_ACTIVE
                    fill_hex = "#ef4444"  # Rojo intenso: Quemándose / ignición activa
                elif code == 2:
                    cat_name = config.FIRE_ZONE_ALREADY_BURNED
                    fill_hex = "#78350f"  # Marrón oscuro/ceniza: Ya quemado
                else:
                    cat_name = config.FIRE_ZONE_THRESHOLD_BUFFER
                    fill_hex = "#f97316"  # Naranja ámbar: Sin quemar pero > safe_fire_threshold

                geojson_features.append(
                    {
                        "type": "Feature",
                        "id": f"{zone_id}_cell_{r}_{c}",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [poly_coords],
                        },
                        "properties": {
                            "feature_type": "fire_cell",
                            "zone_id": zone_id,
                            "cell_id": format_cell_id(c_iy, c_ix),
                            "grid_rc": [r, c],
                            "elevation_m": round(float(elev_2d[r, c]), 1),
                            "cata_quadrant_state": st_cata,
                            "fire_zone_category": cat_name,
                            "is_burning_active": code == 3,
                            "is_already_burned": code == 2,
                            "exceeds_safe_threshold": code in (1, 3),
                            "fire_probability_t1": round(float(probs_2d[r, c]), 4),
                            "reference_date": ref_date,
                            "predicted_date": pred_date,
                            "fill_color": fill_hex,
                            "fill_opacity": 0.65 if code == 3 else (0.50 if code == 2 else 0.35),
                        },
                    }
                )

    zone_summary = {
        "zone_id": zone_id,
        "reference_date": ref_date,
        "predicted_date": pred_date,
        "origins_evaluated": len(origins_rc),
        "routes_generated": routes_found,
        "meeting_points_total": len(meeting_points),
        "meeting_points_safe": len(safe_mp_targets),
        "meeting_points": meeting_points,
        "safe_havens_reached": len(reached_havens),
        "osm_road_coverage": round(float(road_grids.get("coverage", 0.0)), 3),
        "open_elevation_coverage": round(float(elevation_grids.get("coverage", 0.0)), 3),
        "zone_min_elevation_m": round(float(elev_2d.min()), 1),
        "zone_max_elevation_m": round(float(elev_2d.max()), 1),
        "cells_with_roads": int((road_grids["road_access"] > 0.0).sum()),
        "cells_burning_active": int(safety_info["burning_active_mask"].sum()),
        "cells_already_burned": int(safety_info["already_burned_mask"].sum()),
        "cells_threshold_buffer_unsafe": int(safety_info["threshold_unsafe_mask"].sum()),
        "cells_safe_unburned": int(safety_info["safe_unburned_mask"].sum()),
    }
    return geojson_features, zone_summary


def generate_lucia_geojson_from_cata(
    cata_predictions_path: str = config.DEFAULT_CATA_PREDICTIONS_PATH,
    output_geojson_path: str | None = config.DEFAULT_GEOJSON_OUTPUT_PATH,
    model_path: str | None = config.DEFAULT_MODEL_PATH,
    safe_fire_threshold: float = config.SAFE_FIRE_THRESHOLD,
    profiles: Sequence[EvacuationProfile] = ("human", "animal"),
    zone_filter: str | None = None,
    include_fire_polygons: bool = True,
    custom_meeting_points: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ejecuta el eslabón final de la pipeline **VALEN -> CATA -> LUCIA** y exporta el GeoJSON.

    Lee `cata_predictions.json`, aplica el modelo TensorFlow de LUCIA (15 canales con Open-Elevation),
    calcula las rutas más cortas y seguras hacia Puntos de Encuentro (`meeting_point`) teniendo en
    cuenta cambios de elevación (`Δz`) y escribe `lucia_routes.geojson`.
    """
    if not os.path.exists(cata_predictions_path):
        raise FileNotFoundError(
            f"No se encontró el archivo de predicciones de CATA en {cata_predictions_path}"
        )

    with open(cata_predictions_path, encoding="utf-8") as f:
        cata_data = json.load(f)

    model: keras.Model | None = None
    if model_path and os.path.exists(model_path):
        try:
            model = load_lucia_model(model_path, compile_model_flag=False)
        except Exception as exc:
            logger.warning("No se pudo cargar el modelo TF de LUCIA (%s): %s", model_path, exc)

    roads_index = load_roads_index()
    elevation_index = load_elevation_index()

    # Agrupar active_and_predicted_cells por zone_id para enriquecer los canales de VALEN
    cells_by_zone: dict[str, list[dict]] = {}
    for cell in cata_data.get("active_and_predicted_cells", []):
        zid = str(cell.get("zone_id", ""))
        cells_by_zone.setdefault(zid, []).append(cell)

    all_features: list[dict[str, Any]] = []
    zone_summaries: list[dict[str, Any]] = []

    for zone in cata_data.get("zones", []):
        zid = str(zone.get("zone_id", ""))
        if zone_filter and zid != zone_filter:
            continue
        feats, z_sum = build_zone_geojson_features(
            zone=zone,
            active_cells_for_zone=cells_by_zone.get(zid, []),
            model=model,
            profiles=profiles,
            custom_meeting_points=custom_meeting_points,
            safe_fire_threshold=safe_fire_threshold,
            include_fire_polygons=include_fire_polygons,
            roads_index=roads_index,
            elevation_index=elevation_index,
        )
        all_features.extend(feats)
        zone_summaries.append(z_sum)

    geojson_payload: dict[str, Any] = {
        "type": "FeatureCollection",
        "metadata": {
            "algorithm": config.ALGORITHM_NAME,
            "pipeline": list(config.PIPELINE_CHAIN),
            "source_cata_file": os.path.basename(cata_predictions_path),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "crs": config.OUTPUT_GEOJSON_CRS,
            "source_grid_crs": config.GRID_CRS,
            "cell_size_m": config.CELL_SIZE_M,
            "safe_fire_threshold": safe_fire_threshold,
            "safe_haven_max_prob": config.SAFE_HAVEN_MAX_PROB,
            "min_safe_distance_cells": config.MIN_SAFE_DISTANCE_CELLS,
            "elevation_source": "VALEN Open-Elevation (cell_elevation.json + Tobler slope Δz)",
            "meeting_points_enabled": True,
            "tensorflow_model_used": bool(model is not None),
            "total_zones_processed": len(zone_summaries),
            "total_routes_generated": sum(z["routes_generated"] for z in zone_summaries),
            "total_meeting_points": sum(z["meeting_points_total"] for z in zone_summaries),
            "total_features": len(all_features),
            "frontend_style_guide": {
                "evacuation_route_human": {"color": "#10b981", "width": 5, "label": "Ruta Segura Personas"},
                "evacuation_route_animal": {"color": "#38bdf8", "width": 4, "label": "Ruta Segura Animales"},
                "evacuation_origin": {"color": "#f59e0b", "symbol": "warning", "label": "Punto de Inicio en Riesgo"},
                "meeting_point": {"color": "#22c55e", "symbol": "meeting-point", "label": "Punto de Encuentro Seguro"},
                "safe_haven": {"color": "#22c55e", "symbol": "shelter", "label": "Zona Libre de Peligro"},
                "BURNING_ACTIVE": {"color": "#ef4444", "opacity": 0.65, "label": "Quemándose / Predicción Activa"},
                "ALREADY_BURNED": {"color": "#78350f", "opacity": 0.50, "label": "Zona Ya Quemada"},
                "THRESHOLD_BUFFER_UNSAFE": {"color": "#f97316", "opacity": 0.35, "label": "Sin Quemar (> Threshold Seguro)"},
            },
            "zones": zone_summaries,
        },
        "features": all_features,
    }

    if output_geojson_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_geojson_path)), exist_ok=True)
        with open(output_geojson_path, "w", encoding="utf-8") as f:
            json.dump(geojson_payload, f, ensure_ascii=False, indent=2)
        logger.info(
            "GeoJSON de LUCIA exportado en %s (zonas=%d, rutas=%d, meeting_points=%d, features=%d)",
            output_geojson_path,
            len(zone_summaries),
            geojson_payload["metadata"]["total_routes_generated"],
            geojson_payload["metadata"]["total_meeting_points"],
            len(all_features),
        )

    return geojson_payload


def compute_Interactive_route_from_lonlat(
    lon: float,
    lat: float,
    profile: EvacuationProfile = "human",
    safe_fire_threshold: float = config.SAFE_FIRE_THRESHOLD,
    meeting_points: Sequence[dict[str, Any]] | None = None,
    cata_predictions_path: str = config.DEFAULT_CATA_PREDICTIONS_PATH,
    model_path: str | None = config.DEFAULT_MODEL_PATH,
) -> dict[str, Any]:
    """Calcula en tiempo real una ruta GeoJSON desde `(lon, lat)` hacia el Punto de Encuentro más seguro."""
    with open(cata_predictions_path, encoding="utf-8") as f:
        cata_data = json.load(f)

    target_iy, target_ix = lonlat_to_cell_iy_ix(lon, lat)
    zones = cata_data.get("zones", [])
    if not zones:
        return {"type": "FeatureCollection", "features": []}

    # Buscar la zona que contiene (target_iy, target_ix) o la más cercana
    best_zone = None
    best_dist = float("inf")
    best_rc = (0, 0)

    for z in zones:
        y0 = int(z.get("origin_iy", 0))
        x0 = int(z.get("origin_ix", 0))
        h, w = z.get("grid_shape", [config.GRID_SIZE, config.GRID_SIZE])
        r = max(0, min(int(h) - 1, target_iy - y0))
        c = max(0, min(int(w) - 1, target_ix - x0))
        iy_clamped = y0 + r
        ix_clamped = x0 + c
        dist = math.hypot(target_iy - iy_clamped, target_ix - ix_clamped)
        if dist < best_dist:
            best_dist = dist
            best_zone = z
            best_rc = (r, c)

    if best_zone is None:
        return {"type": "FeatureCollection", "features": []}

    model: keras.Model | None = None
    if model_path and os.path.exists(model_path):
        try:
            model = load_lucia_model(model_path, compile_model_flag=False)
        except Exception:
            model = None

    zid = str(best_zone["zone_id"])
    cells_for_zone = [
        c for c in cata_data.get("active_and_predicted_cells", []) if str(c.get("zone_id")) == zid
    ]

    feats, z_sum = build_zone_geojson_features(
        zone=best_zone,
        active_cells_for_zone=cells_for_zone,
        model=model,
        profiles=(profile,),
        custom_origins_rc=[best_rc],
        custom_meeting_points=meeting_points,
        safe_fire_threshold=safe_fire_threshold,
        include_fire_polygons=True,
        roads_index=load_roads_index(),
        elevation_index=load_elevation_index(),
    )
    return {
        "type": "FeatureCollection",
        "metadata": {
            "algorithm": config.ALGORITHM_NAME,
            "pipeline": list(config.PIPELINE_CHAIN),
            "requested_lonlat": [round(lon, 6), round(lat, 6)],
            "matched_zone_id": zid,
            "matched_grid_rc": list(best_rc),
            "profile": profile,
            "safe_fire_threshold": safe_fire_threshold,
            "custom_meeting_points_supplied": len(meeting_points) if meeting_points else 0,
            "zone_summary": z_sum,
        },
        "features": feats,
    }
