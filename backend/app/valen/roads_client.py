#!/usr/bin/env python3
"""
Algoritmo VALEN (Fase 3d) — Cliente de carreteras y caminos: OpenStreetMap (Overpass API).

Descarga la red viaria de OSM (`way["highway"]`) por bloques de celdas ES1K, la proyecta a
EPSG:3035 y la rasteriza sobre la rejilla de 1 km x 1 km para que LUCIA pueda priorizar
carreteras, pistas forestales y senderos al calcular rutas de evacuación.

Por cada celda (`cell_id`) se genera:
  - `road_length_km` total y desglosado por grupo (`major`, `secondary`, `local`, `track`, `path`).
  - `best_highway_class`: la vía más rápida presente en la celda (con >= 200 m de longitud).
  - `road_access_score` [0, 1]: densidad viaria ponderada por jerarquía (1 = muy bien comunicada).
  - `human_speed_factor`: multiplicador de coste de paso a pie/vehículo (< 1 = más rápido que campo a través).
  - `animal_speed_factor`: multiplicador para fauna/ganado (las autovías valladas son barrera, > 1).
  - `motorway_barrier`: True si hay autopista/autovía (vallado perimetral para animales).

No inventa carreteras: si Overpass no responde, el bloque se marca `osm_status = "unavailable"`
y LUCIA trata esas celdas como campo a través (factor 1.0).

Uso:
    # Precalcular las carreteras de las zonas que CATA ha predicho:
    python -m app.valen.roads_client --from-cata app/cata/artifacts/predictions/cata_predictions.json

    # O cubrir todas las celdas de cell_day.parquet (bloques de 32 km):
    python -m app.valen.roads_client --cell-day app/valen/output/cell_day.parquet --limit-blocks 10

Salida: `app/valen/output/cell_roads.json` (array JSON de registros por celda)
Cache:  `app/valen/cache/roads_cache.sqlite` (respuestas Overpass por bbox)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .laea import (
        CELL_SIZE_M,
        cell_block_bbox_lonlat,
        format_cell_id,
        lonlat_to_epsg3035,
        parse_cell_id,
    )
except ImportError:  # ejecución directa como script
    from laea import (  # type: ignore[no-redef]
        CELL_SIZE_M,
        cell_block_bbox_lonlat,
        format_cell_id,
        lonlat_to_epsg3035,
        parse_cell_id,
    )

ALGORITHM_NAME: str = "valen"

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "CATACLISMO-VALEN/0.1 (NASA Space Apps 2026; evacuation routing research)"
REQUEST_TIMEOUT_S = 180
REQUEST_PAUSE_S = 1.5  # cortesía con el servidor público de Overpass

DEFAULT_CACHE_DIR = Path(__file__).parent / "cache"
DEFAULT_CACHE_DB = DEFAULT_CACHE_DIR / "roads_cache.sqlite"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"
DEFAULT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / "cell_roads.json"

DEFAULT_BLOCK_SIZE = 32  # celdas (= tamaño de zona de CATA/LUCIA)
SAMPLE_STEP_M = 50.0  # resolución de rasterizado a lo largo de cada vía

# highway -> (grupo, factor_humano, factor_animal)
#   factor < 1: más rápido que campo a través ; factor > 1: más lento / barrera
HIGHWAY_CLASSES: dict[str, tuple[str, float, float]] = {
    "motorway": ("major", 0.40, 1.40),
    "motorway_link": ("major", 0.45, 1.30),
    "trunk": ("major", 0.42, 1.25),
    "trunk_link": ("major", 0.47, 1.20),
    "primary": ("major", 0.45, 1.00),
    "primary_link": ("major", 0.50, 1.00),
    "secondary": ("secondary", 0.50, 0.95),
    "secondary_link": ("secondary", 0.55, 0.95),
    "tertiary": ("secondary", 0.55, 0.90),
    "tertiary_link": ("secondary", 0.58, 0.90),
    "unclassified": ("local", 0.60, 0.85),
    "residential": ("local", 0.62, 1.00),
    "living_street": ("local", 0.65, 1.00),
    "service": ("local", 0.65, 0.90),
    "track": ("track", 0.72, 0.78),
    "path": ("path", 0.85, 0.80),
    "footway": ("path", 0.85, 0.85),
    "bridleway": ("path", 0.85, 0.78),
    "cycleway": ("path", 0.82, 0.85),
}
GROUP_WEIGHTS: dict[str, float] = {
    "major": 1.0,
    "secondary": 0.9,
    "local": 0.7,
    "track": 0.6,
    "path": 0.4,
}
ROAD_GROUPS: tuple[str, ...] = tuple(GROUP_WEIGHTS)
MOTORWAY_TAGS = {"motorway", "motorway_link", "trunk", "trunk_link"}
MIN_BEST_CLASS_KM = 0.2


class RoadsUnavailableError(RuntimeError):
    """Overpass no responde (sin red, rate limit o timeout)."""


# ---------------------------------------------------------------------------
# Cache SQLite de respuestas Overpass
# ---------------------------------------------------------------------------
class RoadsCache:
    def __init__(self, db_path: Path = DEFAULT_CACHE_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS overpass_bbox (
                    cache_key TEXT PRIMARY KEY,
                    bbox TEXT NOT NULL,
                    n_ways INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def make_key(bbox: tuple[float, float, float, float]) -> str:
        return hashlib.sha256(",".join(f"{v:.5f}" for v in bbox).encode()).hexdigest()[:24]

    def get(self, bbox: tuple[float, float, float, float]) -> list[dict] | None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            row = conn.execute(
                "SELECT payload FROM overpass_bbox WHERE cache_key = ?", (self.make_key(bbox),)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, bbox: tuple[float, float, float, float], ways: list[dict]) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO overpass_bbox VALUES (?, ?, ?, ?, ?)",
                (
                    self.make_key(bbox),
                    json.dumps(bbox),
                    len(ways),
                    json.dumps(ways, separators=(",", ":")),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def stats(self) -> dict:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            n, ways = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(n_ways), 0) FROM overpass_bbox"
            ).fetchone()
        return {"bboxes": n, "ways": ways, "size_mb": round(self.db_path.stat().st_size / 2**20, 2)}


# ---------------------------------------------------------------------------
# Rasterizado de vías sobre la rejilla ES1K
# ---------------------------------------------------------------------------
def rasterize_ways(
    ways: list[dict], cell_size_m: float = CELL_SIZE_M
) -> dict[tuple[int, int], dict[str, Any]]:
    """Reparte la longitud de cada vía entre las celdas `(iy, ix)` que atraviesa."""
    acc: dict[tuple[int, int], dict[str, Any]] = defaultdict(
        lambda: {"len_m": defaultdict(float), "tags": set()}
    )
    for way in ways:
        tag = way.get("highway")
        if tag not in HIGHWAY_CLASSES:
            continue
        pts = [lonlat_to_epsg3035(p["lon"], p["lat"]) for p in way.get("geometry", [])]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
            seg_len = math.hypot(x1 - x0, y1 - y0)
            if seg_len <= 0:
                continue
            n = max(1, int(math.ceil(seg_len / SAMPLE_STEP_M)))
            piece = seg_len / n
            for k in range(n):
                t = (k + 0.5) / n
                ix = int(math.floor((x0 + t * (x1 - x0)) / cell_size_m))
                iy = int(math.floor((y0 + t * (y1 - y0)) / cell_size_m))
                cell = acc[(iy, ix)]
                cell["len_m"][tag] += piece
                cell["tags"].add(tag)
    return acc


def summarize_cell(iy: int, ix: int, cell: dict[str, Any] | None) -> dict[str, Any]:
    """Convierte las longitudes por etiqueta OSM en las features que consume LUCIA."""
    len_by_tag: dict[str, float] = dict(cell["len_m"]) if cell else {}
    group_km = {g: 0.0 for g in ROAD_GROUPS}
    for tag, meters in len_by_tag.items():
        group_km[HIGHWAY_CLASSES[tag][0]] += meters / 1000.0

    total_km = sum(group_km.values())
    access = min(1.0, sum(GROUP_WEIGHTS[g] * km for g, km in group_km.items()) / 2.0)

    def _best(idx: int) -> tuple[str | None, float]:
        candidates = [
            (HIGHWAY_CLASSES[t][idx], t, m / 1000.0)
            for t, m in len_by_tag.items()
            if m / 1000.0 >= MIN_BEST_CLASS_KM
        ]
        if not candidates:
            return None, 1.0
        factor, tag, km = min(candidates)
        coverage = min(1.0, km / 1.0)  # 1 km de vía en una celda de 1 km = cobertura total
        return tag, 1.0 + (factor - 1.0) * coverage

    best_tag, human_factor = _best(1)
    _, animal_factor = _best(2)
    barrier = any(t in MOTORWAY_TAGS for t in len_by_tag)
    if barrier:
        animal_factor = max(animal_factor, 1.2)

    return {
        "cell_id": format_cell_id(iy, ix),
        "iy": iy,
        "ix": ix,
        "road_length_km": round(total_km, 3),
        **{f"road_{g}_km": round(km, 3) for g, km in group_km.items()},
        "best_highway_class": best_tag,
        "highway_tags": sorted(len_by_tag),
        "road_access_score": round(access, 4),
        "human_speed_factor": round(human_factor, 4),
        "animal_speed_factor": round(animal_factor, 4),
        "motorway_barrier": barrier,
        "osm_status": "ok",
        "source": "OpenStreetMap (Overpass API) © OpenStreetMap contributors, ODbL",
    }


def unavailable_cell(iy: int, ix: int) -> dict[str, Any]:
    return {
        "cell_id": format_cell_id(iy, ix),
        "iy": iy,
        "ix": ix,
        "road_length_km": 0.0,
        **{f"road_{g}_km": 0.0 for g in ROAD_GROUPS},
        "best_highway_class": None,
        "highway_tags": [],
        "road_access_score": 0.0,
        "human_speed_factor": 1.0,
        "animal_speed_factor": 1.0,
        "motorway_barrier": False,
        "osm_status": "unavailable",
        "source": "OpenStreetMap (Overpass API) — no disponible en la consulta",
    }


# ---------------------------------------------------------------------------
# Cliente principal
# ---------------------------------------------------------------------------
class RoadsClient:
    """Cliente OSM/Overpass con cache por bbox y rasterizado a celdas ES1K."""

    def __init__(
        self,
        cache: RoadsCache | None = None,
        overpass_url: str = OVERPASS_URL,
        timeout_s: int = REQUEST_TIMEOUT_S,
    ):
        self.cache = cache or RoadsCache()
        self.overpass_url = overpass_url
        self.timeout_s = timeout_s
        self._last_request = 0.0

    @staticmethod
    def build_query(bbox: tuple[float, float, float, float]) -> str:
        s, w, n, e = bbox
        tags = "|".join(HIGHWAY_CLASSES)
        return (
            f"[out:json][timeout:{REQUEST_TIMEOUT_S}];"
            f'way["highway"~"^({tags})$"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});'
            "out tags geom;"
        )

    def fetch_ways_bbox(
        self, bbox: tuple[float, float, float, float], use_cache: bool = True
    ) -> list[dict]:
        """Devuelve `[{"id", "highway", "geometry": [{"lat", "lon"}, ...]}, ...]` del bbox."""
        if use_cache:
            cached = self.cache.get(bbox)
            if cached is not None:
                return cached

        wait = REQUEST_PAUSE_S - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        body = urllib.parse.urlencode({"data": self.build_query(bbox)}).encode()
        req = urllib.request.Request(
            self.overpass_url, data=body, headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise RoadsUnavailableError(f"Overpass no disponible para bbox {bbox}: {exc}") from exc
        finally:
            self._last_request = time.monotonic()

        ways = [
            {
                "id": el.get("id"),
                "highway": el.get("tags", {}).get("highway"),
                "geometry": el.get("geometry", []),
            }
            for el in payload.get("elements", [])
            if el.get("type") == "way" and el.get("geometry")
        ]
        self.cache.set(bbox, ways)
        return ways

    def cells_for_block(
        self,
        origin_iy: int,
        origin_ix: int,
        height: int = DEFAULT_BLOCK_SIZE,
        width: int = DEFAULT_BLOCK_SIZE,
        use_cache: bool = True,
    ) -> dict[str, dict[str, Any]]:
        """Features viarias de todas las celdas del bloque `[origin, origin + (h, w))`."""
        bbox = cell_block_bbox_lonlat(origin_iy, origin_ix, height, width)
        cells = {}
        try:
            raster = rasterize_ways(self.fetch_ways_bbox(bbox, use_cache=use_cache))
            builder = lambda iy, ix: summarize_cell(iy, ix, raster.get((iy, ix)))  # noqa: E731
        except RoadsUnavailableError as exc:
            print(f"  AVISO {exc}")
            builder = unavailable_cell
        for iy in range(origin_iy, origin_iy + height):
            for ix in range(origin_ix, origin_ix + width):
                rec = builder(iy, ix)
                cells[rec["cell_id"]] = rec
        return cells

    # ---- Orquestación ----

    def build_from_blocks(
        self,
        blocks: list[tuple[int, int, int, int]],
        output_path: Path = DEFAULT_OUTPUT_PATH,
        use_cache: bool = True,
    ) -> dict[str, dict[str, Any]]:
        merged = load_cell_roads(output_path) if Path(output_path).exists() else {}
        for i, (oy, ox, h, w) in enumerate(blocks, 1):
            print(f"[{i}/{len(blocks)}] Bloque Y{oy:05d} X{ox:05d} ({h}x{w} km)")
            block = self.cells_for_block(oy, ox, h, w, use_cache=use_cache)
            for cid, rec in block.items():
                # Nunca sobrescribir datos OSM válidos con un bloque "unavailable"
                if rec["osm_status"] == "ok" or cid not in merged:
                    merged[cid] = rec
            ok = sum(1 for r in block.values() if r["road_length_km"] > 0)
            print(f"    celdas con vías: {ok}/{len(block)}")
        save_cell_roads(merged, output_path)
        print(f"Guardado {len(merged)} celdas en {output_path} | cache: {self.cache.stats()}")
        return merged


# ---------------------------------------------------------------------------
# Utilidades de entrada/salida
# ---------------------------------------------------------------------------
def save_cell_roads(records: dict[str, dict[str, Any]], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from .json_output import JSONArrayWriter
    except ImportError:
        from json_output import JSONArrayWriter  # type: ignore[no-redef]
    with JSONArrayWriter(output_path, indent=2) as w:
        for rec in sorted(records.values(), key=lambda r: (r["iy"], r["ix"])):
            w.write(rec)


def load_cell_roads(path: Path | str = DEFAULT_OUTPUT_PATH) -> dict[str, dict[str, Any]]:
    """Índice `{cell_id: registro}` de `cell_roads.json` (vacío si no existe)."""
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VALEN — Carreteras y caminos OSM por celda ES1K")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-cata", type=Path, help="cata_predictions.json (bloques de sus zonas)")
    src.add_argument("--cell-day", type=Path, help="cell_day.parquet/json (bloques que lo cubren)")
    src.add_argument(
        "--block", nargs=4, type=int, metavar=("ORIGIN_IY", "ORIGIN_IX", "H", "W"),
        help="Bloque explícito de celdas ES1K",
    )
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    p.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE)
    p.add_argument("--limit-blocks", type=int, default=None)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--overpass-url", default=OVERPASS_URL)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    if args.from_cata:
        blocks = blocks_from_cata(args.from_cata)
    elif args.cell_day:
        blocks = blocks_from_cell_day(args.cell_day, args.block_size)
    else:
        blocks = [tuple(args.block)]
    if args.limit_blocks:
        blocks = blocks[: args.limit_blocks]
    print(f"VALEN roads: {len(blocks)} bloques a consultar en OSM")
    RoadsClient(overpass_url=args.overpass_url).build_from_blocks(
        blocks, output_path=args.output, use_cache=not args.no_cache
    )


if __name__ == "__main__":
    main()
