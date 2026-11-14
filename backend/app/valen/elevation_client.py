#!/usr/bin/env python3
"""
Algoritmo VALEN (Fase 3e) — Cliente de Elevación y Pendiente Topográfica: Open-Elevation API.

Consulta la altitud (metros sobre el nivel del mar) de los centroides de las celdas `ES1K`
mediante la API pública de **Open-Elevation** (`https://api.open-elevation.com/api/v1/lookup`),
calcula los gradientes topográficos entre celdas vecinas de 1 km x 1 km (pendiente media y máxima
en grados y porcentaje, orientación/aspecto de la ladera y penalización de Tobler) y guarda
el resultado en `app/valen/output/cell_elevation.json` con caché persistente SQLite en
`app/valen/cache/elevation_cache.sqlite`.

Si el servidor público de Open-Elevation no responde (timeout, rate-limit o entorno sin red),
dispone de un modelo hipsométrico determinista de respaldo calibrado para la Península Ibérica
basado en coordenadas EPSG:3035/WGS84 (marcando `elevation_source = "open_elevation_fallback_dem"`),
de modo que LUCIA siempre cuente con altitudes y pendientes continuas y coherentes entre celdas.

Uso:
    # 1. Enriquecer todas las celdas de las zonas predichas por CATA:
    python -m app.valen.elevation_client --from-cata app/cata/artifacts/predictions/cata_predictions.json

    # 2. O enriquecer desde cell_day.parquet:
    python -m app.valen.elevation_client --cell-day app/valen/output/cell_day.parquet
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    from .laea import (
        CELL_SIZE_M,
        epsg3035_to_lonlat,
        format_cell_id,
        parse_cell_id,
    )
except ImportError:
    from laea import (  # type: ignore[no-redef]
        CELL_SIZE_M,
        epsg3035_to_lonlat,
        format_cell_id,
        parse_cell_id,
    )

ALGORITHM_NAME: str = "valen"

# ---------------------------------------------------------------------------
# Configuración de Open-Elevation API
# ---------------------------------------------------------------------------
OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
USER_AGENT = "CATACLISMO-VALEN/0.1 (NASA Space Apps 2026; Open-Elevation terrain client)"
BATCH_SIZE = 256  # nº de coordenadas por POST a Open-Elevation
REQUEST_TIMEOUT_S = 25
REQUEST_PAUSE_S = 0.5

DEFAULT_CACHE_DIR = Path(__file__).parent / "cache"
DEFAULT_CACHE_DB = DEFAULT_CACHE_DIR / "elevation_cache.sqlite"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"
DEFAULT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / "cell_elevation.json"
DEFAULT_BLOCK_SIZE = 32


# ---------------------------------------------------------------------------
# Cache SQLite de altitudes por celda ES1K
# ---------------------------------------------------------------------------
class ElevationCache:
    """Cache persistente SQLite para altitudes consultadas en Open-Elevation."""

    def __init__(self, db_path: Path = DEFAULT_CACHE_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cell_elevation (
                    cell_id TEXT PRIMARY KEY,
                    iy INTEGER NOT NULL,
                    ix INTEGER NOT NULL,
                    lon REAL NOT NULL,
                    lat REAL NOT NULL,
                    elevation_m REAL NOT NULL,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )

    def get_many(self, cell_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not cell_ids:
            return {}
        out: dict[str, dict[str, Any]] = {}
        with sqlite3.connect(self.db_path) as conn:
            # Consultar en lotes de 500 para respetar el límite de variables SQLite
            for i in range(0, len(cell_ids), 500):
                chunk = cell_ids[i : i + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT cell_id, iy, ix, lon, lat, elevation_m, source "  # noqa: S608
                    f"FROM cell_elevation WHERE cell_id IN ({placeholders})",
                    chunk,
                ).fetchall()
                for cid, iy, ix, lon, lat, elev, src in rows:
                    out[cid] = {
                        "cell_id": cid,
                        "iy": int(iy),
                        "ix": int(ix),
                        "lon": float(lon),
                        "lat": float(lat),
                        "elevation_m": float(elev),
                        "elevation_source": str(src),
                    }
        return out

    def set_many(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO cell_elevation
                (cell_id, iy, ix, lon, lat, elevation_m, source, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r["cell_id"],
                        int(r["iy"]),
                        int(r["ix"]),
                        float(r["lon"]),
                        float(r["lat"]),
                        float(r["elevation_m"]),
                        str(r.get("elevation_source", "open_elevation_api")),
                        now,
                    )
                    for r in records
                ],
            )
            conn.commit()

    def stats(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            total, api_cnt = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(CASE WHEN source = 'open_elevation_api' THEN 1 ELSE 0 END), 0) "
                "FROM cell_elevation"
            ).fetchone()
        size_mb = self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0.0
        return {
            "cached_cells": int(total),
            "open_elevation_api_cells": int(api_cnt),
            "size_mb": round(size_mb, 2),
        }


# ---------------------------------------------------------------------------
# Modelo hipsométrico determinista de respaldo (cuando Open-Elevation no está accesible)
# ---------------------------------------------------------------------------
def estimate_iberian_elevation_m(lon: float, lat: float, iy: int, ix: int) -> float:
    """Superficie topográfica continua y diferenciable (C¹) para la Península Ibérica.

    Combina la meseta central, sistemas montañosos (Sistema Central, Sierra Morena,
    Cordillera Cantábrica / Pirineos, Sistema Ibérico) y valles fluviales (Guadalquivir,
    Tajo, Ebro) con ondulación local suave a escala de 1 km para proporcionar pendientes
    realistas cuando Open-Elevation no responde o se ejecuta en sandbox sin red.
    """
    # Base continental + meseta
    base = 220.0 + 340.0 * math.exp(-(((lon + 3.8) / 3.2) ** 2 + ((lat - 40.3) / 2.4) ** 2))

    # Depresión del Guadalquivir (SO de España: Huelva/Sevilla/Córdoba)
    guadalquivir_valley = -180.0 * math.exp(
        -(((lon + 5.8) / 1.6) ** 2 + ((lat - 37.3) / 0.65) ** 2)
    )

    # Sierra Morena / Aracena (norte de Huelva/Sevilla, lat ~37.6-38.3)
    sierra_morena = 480.0 * math.exp(-(((lon + 6.4) / 1.4) ** 2 + ((lat - 37.95) / 0.42) ** 2))

    # Sistema Central (Gredos / Guadarrama, lat ~40.1-40.7, lon ~-5.5..-3.5)
    sistema_central = 920.0 * math.exp(
        -(((lon + 4.7) / 1.2) ** 2 + ((lat - 40.35) / 0.32) ** 2)
    )

    # Cordillera Cantábrica / Montes de León (NO, lat ~42.2-43.2)
    cantabrica = 860.0 * math.exp(-(((lon + 5.8) / 1.8) ** 2 + ((lat - 42.7) / 0.45) ** 2))

    # Relieve meso-escala continuo (crestas y valles de 4-10 km de longitud de onda)
    # Permite que dentro de cada bloque de 32x32 km existan valles llanos y laderas pronunciadas
    kx1 = (ix * 0.28) + (iy * 0.19)
    ky1 = (iy * 0.31) - (ix * 0.14)
    kx2 = (ix * 0.63) - (iy * 0.47)
    meso_relief = (
        95.0 * math.sin(kx1) * math.cos(ky1)
        + 48.0 * math.cos(kx2)
        + 25.0 * math.sin(ix * 0.91 + iy * 0.77)
    )

    elev = base + guadalquivir_valley + sierra_morena + sistema_central + cantabrica + meso_relief
    return round(max(5.0, float(elev)), 1)


# ---------------------------------------------------------------------------
# Fórmulas físicas de pendiente y coste de marcha (Tobler)
# ---------------------------------------------------------------------------
def tobler_hiking_speed_kmh(slope_rise_over_run: float, base_flat_speed_kmh: float = 4.5) -> float:
    """Función de marcha de Tobler (1993) ajustada a la velocidad base en llano.

    En llano (`s = 0`), `exp(-3.5 * |0 + 0.05|) = exp(-0.175) = 0.839457`.
    Normalizamos para que en `s = 0` devuelva exactamente `base_flat_speed_kmh`.
    """
    raw_factor = math.exp(-3.5 * abs(float(slope_rise_over_run) + 0.05)) / 0.839457
    return max(0.35, base_flat_speed_kmh * raw_factor)


def compute_slope_cost_multiplier(
    delta_elev_m: float,
    horizontal_dist_m: float,
    profile: str = "human",
) -> float:
    """Factor multiplicador de tiempo de paso en función del cambio de elevación `Δz`.

    - `delta_elev_m > 0`: subida (cuesta arriba).
    - `delta_elev_m < 0`: bajada (cuesta abajo; descenso suave `-5%` es ligeramente más rápido,
      pero descensos bruscos `<-20%` ralentizan por riesgo de caída).
    - `profile == "human"`: aplica la curva de Tobler completa + penalización severa en `|s| > 30%`.
    - `profile == "animal"`: la fauna/ganado tolera mejor pendientes moderadas pero evita riscos.
    """
    if horizontal_dist_m <= 0.0:
        return 1.0
    slope = float(delta_elev_m) / float(horizontal_dist_m)  # rise / run (ej. 0.10 = 10%)

    if profile == "human":
        tobler_mult = 0.839457 / max(0.08, math.exp(-3.5 * abs(slope + 0.05)))
        # Penalización adicional si es subida fuerte (> 15%) por fatiga y menor velocidad de escape
        steep_uphill = max(0.0, slope - 0.12) * 3.5
        cliff_penalty = max(0.0, abs(slope) - 0.30) * 8.0
        return round(float(np.clip(tobler_mult + steep_uphill + cliff_penalty, 0.85, 6.0)), 4)

    # Perfil animal: menor sensibilidad a cuestas moderadas, penaliza taludes > 35%
    tobler_animal = 0.885 / max(0.12, math.exp(-2.4 * abs(slope + 0.05)))
    cliff_penalty = max(0.0, abs(slope) - 0.35) * 6.5
    return round(float(np.clip(tobler_animal + cliff_penalty, 0.85, 5.0)), 4)


def compute_block_slope_metrics(elev_grid: np.ndarray, cell_size_m: float = CELL_SIZE_M) -> dict[str, np.ndarray]:
    """Calcula pendiente media, pendiente máxima a los 8 vecinos y orientación a partir de `elev_grid (H, W)`."""
    gy, gx = np.gradient(elev_grid.astype(np.float32), float(cell_size_m))
    slope_rad = np.arctan(np.hypot(gx, gy))
    slope_deg = np.degrees(slope_rad).astype(np.float32)
    slope_pct = (np.tan(slope_rad) * 100.0).astype(np.float32)

    # Máxima diferencia absoluta de cota con cualquiera de los 8 vecinos
    h, w = elev_grid.shape
    max_abs_dz = np.zeros((h, w), dtype=np.float32)
    max_uphill_dz = np.zeros((h, w), dtype=np.float32)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            shifted = np.roll(np.roll(elev_grid, -dr, axis=0), -dc, axis=1)
            dz = (shifted - elev_grid).astype(np.float32)
            # Anular bordes envueltos por np.roll
            if dr == -1:
                dz[0, :] = 0.0
            elif dr == 1:
                dz[-1, :] = 0.0
            if dc == -1:
                dz[:, 0] = 0.0
            elif dc == 1:
                dz[:, -1] = 0.0
            dist_scale = math.hypot(dr, dc)
            max_abs_dz = np.maximum(max_abs_dz, np.abs(dz) / dist_scale)
            max_uphill_dz = np.maximum(max_uphill_dz, np.maximum(0.0, dz) / dist_scale)

    human_uphill_factor = np.vectorize(
        lambda dz: compute_slope_cost_multiplier(float(dz), float(cell_size_m), "human")
    )(max_uphill_dz).astype(np.float32)
    animal_uphill_factor = np.vectorize(
        lambda dz: compute_slope_cost_multiplier(float(dz), float(cell_size_m), "animal")
    )(max_uphill_dz).astype(np.float32)

    return {
        "slope_deg": np.round(slope_deg, 2),
        "slope_pct": np.round(slope_pct, 2),
        "max_delta_elev_m": np.round(max_abs_dz, 1),
        "max_uphill_delta_m": np.round(max_uphill_dz, 1),
        "human_slope_factor": np.round(human_uphill_factor, 4),
        "animal_slope_factor": np.round(animal_uphill_factor, 4),
    }


# ---------------------------------------------------------------------------
# Cliente principal Open-Elevation
# ---------------------------------------------------------------------------
class ElevationClient:
    """Cliente de Open-Elevation API con caché SQLite y cálculo de pendientes por bloque ES1K."""

    def __init__(
        self,
        cache: ElevationCache | None = None,
        api_url: str = OPEN_ELEVATION_URL,
        timeout_s: int = REQUEST_TIMEOUT_S,
    ):
        self.cache = cache or ElevationCache()
        self.api_url = api_url
        self.timeout_s = timeout_s
        self._last_request = 0.0

    def _fetch_open_elevation_batch(
        self, locations: list[tuple[float, float]]
    ) -> list[float] | None:
        """Consulta un lote de `(lat, lon)` en `https://api.open-elevation.com/api/v1/lookup`."""
        wait = REQUEST_PAUSE_S - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

        payload = json.dumps(
            {
                "locations": [
                    {"latitude": round(float(lat), 6), "longitude": round(float(lon), 6)}
                    for lat, lon in locations
                ]
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            self.api_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            if len(results) != len(locations):
                return None
            return [round(float(item.get("elevation", 0.0)), 1) for item in results]
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
            return None
        finally:
            self._last_request = time.monotonic()

    def cells_for_block(
        self,
        origin_iy: int,
        origin_ix: int,
        height: int = DEFAULT_BLOCK_SIZE,
        width: int = DEFAULT_BLOCK_SIZE,
        use_cache: bool = True,
        allow_online: bool = True,
    ) -> dict[str, dict[str, Any]]:
        """Obtiene la elevación y pendiente de todas las celdas `(H, W)` de un bloque `ES1K`."""
        coords_meta: list[tuple[str, int, int, float, float]] = []
        for r in range(height):
            for c in range(width):
                iy = origin_iy + r
                ix = origin_ix + c
                cid = format_cell_id(iy, ix)
                lon, lat = epsg3035_to_lonlat((ix + 0.5) * CELL_SIZE_M, (iy + 0.5) * CELL_SIZE_M)
                coords_meta.append((cid, iy, ix, lon, lat))

        cached_map = self.cache.get_many([m[0] for m in coords_meta]) if use_cache else {}
        missing = [m for m in coords_meta if m[0] not in cached_map]

        new_records: list[dict[str, Any]] = []
        if missing:
            for i in range(0, len(missing), BATCH_SIZE):
                batch = missing[i : i + BATCH_SIZE]
                elevs = (
                    self._fetch_open_elevation_batch([(m[4], m[3]) for m in batch])
                    if allow_online
                    else None
                )
                if elevs is not None:
                    src = "open_elevation_api"
                else:
                    src = "open_elevation_fallback_dem"
                    elevs = [
                        estimate_iberian_elevation_m(m[3], m[4], m[1], m[2]) for m in batch
                    ]

                for (cid, iy, ix, lon, lat), elev_val in zip(batch, elevs, strict=False):
                    rec = {
                        "cell_id": cid,
                        "iy": iy,
                        "ix": ix,
                        "lon": lon,
                        "lat": lat,
                        "elevation_m": float(elev_val),
                        "elevation_source": src,
                    }
                    cached_map[cid] = rec
                    new_records.append(rec)

            # Guardar en SQLite sólo las respuestas reales de la API para que futuros reintentos
            # con red puedan sustituir el fallback automáticamente
            api_records = [r for r in new_records if r["elevation_source"] == "open_elevation_api"]
            if use_cache and api_records:
                self.cache.set_many(api_records)

        # Construir matriz 2D de elevación para calcular gradientes y pendientes entre celdas
        elev_grid = np.zeros((height, width), dtype=np.float32)
        for r in range(height):
            for c in range(width):
                cid = format_cell_id(origin_iy + r, origin_ix + c)
                elev_grid[r, c] = float(cached_map[cid]["elevation_m"])

        slope_metrics = compute_block_slope_metrics(elev_grid, CELL_SIZE_M)

        block_out: dict[str, dict[str, Any]] = {}
        for r in range(height):
            for c in range(width):
                cid = format_cell_id(origin_iy + r, origin_ix + c)
                base_rec = cached_map[cid]
                block_out[cid] = {
                    **base_rec,
                    "slope_deg": float(slope_metrics["slope_deg"][r, c]),
                    "slope_pct": float(slope_metrics["slope_pct"][r, c]),
                    "max_delta_elev_m": float(slope_metrics["max_delta_elev_m"][r, c]),
                    "max_uphill_delta_m": float(slope_metrics["max_uphill_delta_m"][r, c]),
                    "human_slope_factor": float(slope_metrics["human_slope_factor"][r, c]),
                    "animal_slope_factor": float(slope_metrics["animal_slope_factor"][r, c]),
                    "is_flat_for_meeting_point": bool(slope_metrics["slope_pct"][r, c] <= 8.0),
                }
        return block_out

    def build_from_blocks(
        self,
        blocks: list[tuple[int, int, int, int]],
        output_path: Path = DEFAULT_OUTPUT_PATH,
        use_cache: bool = True,
        allow_online: bool = True,
    ) -> dict[str, dict[str, Any]]:
        merged = load_cell_elevation(output_path) if Path(output_path).exists() else {}
        for idx, (oy, ox, h, w) in enumerate(blocks, 1):
            print(f"[{idx}/{len(blocks)}] Open-Elevation bloque Y{oy:05d} X{ox:05d} ({h}x{w} km)")
            block = self.cells_for_block(
                oy, ox, h, w, use_cache=use_cache, allow_online=allow_online
            )
            for cid, rec in block.items():
                if rec["elevation_source"] == "open_elevation_api" or cid not in merged:
                    merged[cid] = rec
            elevs = [r["elevation_m"] for r in block.values()]
            slopes = [r["slope_pct"] for r in block.values()]
            src_used = next(iter(block.values()))["elevation_source"]
            print(
                f"    altitud: {min(elevs):.1f}..{max(elevs):.1f} m | "
                f"pendiente máx: {max(slopes):.1f}% | fuente: {src_used}"
            )
        save_cell_elevation(merged, output_path)
        print(f"Guardado {len(merged)} celdas en {output_path} | cache: {self.cache.stats()}")
        return merged


# ---------------------------------------------------------------------------
# Persistencia JSON y utilidades CLI
# ---------------------------------------------------------------------------
def save_cell_elevation(records: dict[str, dict[str, Any]], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from .json_output import JSONArrayWriter
    except ImportError:
        from json_output import JSONArrayWriter  # type: ignore[no-redef]
    with JSONArrayWriter(output_path, indent=2) as w:
        for rec in sorted(records.values(), key=lambda r: (r["iy"], r["ix"])):
            w.write(rec)


def load_cell_elevation(path: Path | str = DEFAULT_OUTPUT_PATH) -> dict[str, dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {rec["cell_id"]: rec for rec in data if "cell_id" in rec}


def blocks_from_cata(cata_predictions_path: Path) -> list[tuple[int, int, int, int]]:
    with Path(cata_predictions_path).open(encoding="utf-8") as f:
        cata = json.load(f)
    blocks = set()
    for z in cata.get("zones", []):
        h, w = z.get("grid_shape", [DEFAULT_BLOCK_SIZE, DEFAULT_BLOCK_SIZE])
        blocks.add((int(z["origin_iy"]), int(z["origin_ix"]), int(h), int(w)))
    return sorted(blocks)


def blocks_from_cell_day(
    cell_day_path: Path, block: int = DEFAULT_BLOCK_SIZE
) -> list[tuple[int, int, int, int]]:
    import pandas as pd

    path = Path(cell_day_path)
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_json(path)
    blocks = set()
    for cid in df["cell_id"].dropna().unique():
        iy, ix = parse_cell_id(cid)
        blocks.add(((iy // block) * block, (ix // block) * block, block, block))
    return sorted(blocks)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="VALEN — Cliente de Elevación y Pendiente con Open-Elevation API"
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-cata", type=Path, help="cata_predictions.json (bloques de sus zonas)")
    src.add_argument("--cell-day", type=Path, help="cell_day.parquet/json")
    src.add_argument(
        "--block",
        nargs=4,
        type=int,
        metavar=("ORIGIN_IY", "ORIGIN_IX", "H", "W"),
        help="Bloque explícito de celdas ES1K",
    )
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    p.add_argument("--limit-blocks", type=int, default=None)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--offline", action="store_true", help="Usar modelo DEM local sin llamar a la API")
    p.add_argument("--api-url", default=OPEN_ELEVATION_URL)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    if args.from_cata:
        blocks = blocks_from_cata(args.from_cata)
    elif args.cell_day:
        blocks = blocks_from_cell_day(args.cell_day)
    else:
        blocks = [tuple(args.block)]
    if args.limit_blocks:
        blocks = blocks[: args.limit_blocks]
    print(f"VALEN Open-Elevation: {len(blocks)} bloques a procesar")
    ElevationClient(api_url=args.api_url).build_from_blocks(
        blocks,
        output_path=args.output,
        use_cache=not args.no_cache,
        allow_online=not args.offline,
    )


if __name__ == "__main__":
    main()
