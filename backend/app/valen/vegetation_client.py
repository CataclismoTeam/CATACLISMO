#!/usr/bin/env python3
"""
Algoritmo VALEN (Fase 3b) — Cliente de vegetación: ESA WorldCover 10m + MITECO IFN3.

- ESA WorldCover 2021: 10m, 11 clases globales, GeoTIFF/COG via AWS S3 / Copernicus
- MITECO IFN3 (Inventario Forestal Nacional): WMS/GeoJSON, especies forestales España
- Cache local de tiles WorldCover
- Lookup rápido por coordenada (centroide celda)
- Mapeo a inflamabilidad por clase
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import requests
from pyproj import Transformer

ALGORITHM_NAME: str = "valen"

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

# ESA WorldCover 2021 (COG en AWS S3 público)
WORLDCOVER_BASE_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v100/2021"
WORLDCOVER_TILE_SIZE = 3 * 3600  # 3° x 3° en segundos = ~330km x 330km
WORLDCOVER_RESOLUTION = 10  # metros

# MITECO IFN3 WMS
IFN3_WMS_URL = "https://www.miteco.gob.es/arcgis/services/IFN3/MapServer/WMSServer"

# Transformador EPSG:3035 -> EPSG:4326 (para WorldCover que está en WGS84)
TRANSFORMER_3035_TO_4326 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)

# Clases WorldCover 2021 (11 clases)
WORLDCOVER_CLASSES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}

# Inflamabilidad relativa por clase WorldCover (1-5, 5=más inflamable)
# Basado en literatura de incendios mediterráneos
FLAMMABILITY_WORLDCOVER = {
    10: 4,   # Tree cover (bosque) - depende de especie
    20: 5,   # Shrubland (matorral) - muy inflamable
    30: 3,   # Grassland (pastizal) - estacional
    40: 2,   # Cropland (cultivos) - bajo salvo rastrojos
    50: 1,   # Built-up (urbano) - muy bajo
    60: 2,   # Bare/sparse - bajo
    70: 1,   # Snow/ice - nulo
    80: 1,   # Water - nulo
    90: 2,   # Wetland - bajo
    95: 3,   # Mangroves - medio
    100: 1,  # Moss/lichen - muy bajo
}

# Especies forestales IFN3 principales en España y su inflamabilidad (1-5)
IFN3_SPECIES_FLAMMABILITY = {
    # Coníferas (alta inflamabilidad)
    "Pinus halepensis": 5,      # Pino carrasco
    "Pinus pinaster": 5,        # Pino rodeno
    "Pinus pinea": 4,           # Pino piñonero
    "Pinus sylvestris": 4,      # Pino silvestre
    "Pinus nigra": 4,           # Pino laricio
    "Pinus uncinata": 3,        # Pino negro
    "Abies alba": 3,            # Abeto
    # Quercus (media-alta)
    "Quercus ilex": 4,          # Encina
    "Quercus suber": 4,         # Alcornoque
    "Quercus pyrenaica": 3,     # Roble melojo
    "Quercus faginea": 3,       # Quejigo
    "Quercus pubescens": 3,     # Roble pubescente
    # Otras frondosas (media-baja)
    "Fagus sylvatica": 2,       # Haya
    "Castanea sativa": 2,       # Castaño
    "Betula pendula": 2,        # Abedul
    "Populus sp.": 2,           # Chopo/álamo
    "Eucalyptus sp.": 5,        # Eucalipto (muy inflamable)
    # Matorrales
    "Cistus sp.": 5,            # Jara
    "Erica sp.": 4,             # Brezo
    "Genista sp.": 4,           # Retama
    "Ulex sp.": 5,              # Aulaga
}

DEFAULT_CACHE_DIR = Path(__file__).parent / "cache"
WORLDCOVER_CACHE_DIR = DEFAULT_CACHE_DIR / "worldcover_tiles"
DEFAULT_CACHE_DB = DEFAULT_CACHE_DIR / "vegetation_cache.sqlite"

# ---------------------------------------------------------------------------
# Cache SQLite
# ---------------------------------------------------------------------------

class VegetationCache:
    """Cache persistente para consultas de vegetación."""

    def __init__(self, db_path: Path = DEFAULT_CACHE_DB):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS worldcover_lookup (
                    cache_key TEXT PRIMARY KEY,
                    lon REAL NOT NULL,
                    lat REAL NOT NULL,
                    class_id INTEGER NOT NULL,
                    class_name TEXT NOT NULL,
                    flammability INTEGER NOT NULL,
                    tile_url TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_wc_coord
                ON worldcover_lookup (lon, lat)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ifn3_lookup (
                    cache_key TEXT PRIMARY KEY,
                    lon REAL NOT NULL,
                    lat REAL NOT NULL,
                    species_list TEXT NOT NULL,
                    dominant_species TEXT,
                    max_flammability INTEGER,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ifn3_coord
                ON ifn3_lookup (lon, lat)
            """)
            conn.commit()

    def _make_key(self, lon: float, lat: float, source: str) -> str:
        raw = f"{source}|{lon:.6f}|{lat:.6f}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # WorldCover
    def get_worldcover(self, lon: float, lat: float) -> dict | None:
        key = self._make_key(lon, lat, "worldcover")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT class_id, class_name, flammability FROM worldcover_lookup WHERE cache_key = ?",
                (key,)
            ).fetchone()
            if row:
                return dict(row)
        return None

    def set_worldcover(self, lon: float, lat: float, class_id: int, tile_url: str = "") -> None:
        key = self._make_key(lon, lat, "worldcover")
        class_name = WORLDCOVER_CLASSES.get(class_id, "Unknown")
        flammability = FLAMMABILITY_WORLDCOVER.get(class_id, 1)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO worldcover_lookup
                (cache_key, lon, lat, class_id, class_name, flammability, tile_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (key, lon, lat, class_id, class_name, flammability, tile_url,
                  datetime.now(timezone.utc).isoformat()))
            conn.commit()

    # IFN3
    def get_ifn3(self, lon: float, lat: float) -> dict | None:
        key = self._make_key(lon, lat, "ifn3")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT species_list, dominant_species, max_flammability FROM ifn3_lookup WHERE cache_key = ?",
                (key,)
            ).fetchone()
            if row:
                return dict(row)
        return None

    def set_ifn3(self, lon: float, lat: float, species_list: list[str],
                 dominant: str, max_flammability: int) -> None:
        key = self._make_key(lon, lat, "ifn3")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO ifn3_lookup
                (cache_key, lon, lat, species_list, dominant_species, max_flammability, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (key, lon, lat, json.dumps(species_list), dominant, max_flammability,
                  datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            wc = conn.execute("SELECT COUNT(*) FROM worldcover_lookup").fetchone()[0]
            ifn3 = conn.execute("SELECT COUNT(*) FROM ifn3_lookup").fetchone()[0]
            size_mb = self.db_path.stat().st_size / (1024 * 1024)
            return {"worldcover_entries": wc, "ifn3_entries": ifn3, "size_mb": round(size_mb, 2)}


# ---------------------------------------------------------------------------
# Utilidades WorldCover
# ---------------------------------------------------------------------------

def lonlat_to_tile(lon: float, lat: float) -> tuple[int, int]:
    """Convierte lon/lat a índices de tile WorldCover (3°x3°)."""
    # Tiles van de -180 a 180 (lon) y -90 a 84 (lat) en pasos de 3°
    tile_x = int(np.floor((lon + 180) / 3))
    tile_y = int(np.floor((lat + 90) / 3))
    return tile_x, tile_y


def tile_to_bbox(tile_x: int, tile_y: int) -> tuple[float, float, float, float]:
    """BBox del tile en lon/lat: (min_lon, min_lat, max_lon, max_lat)."""
    min_lon = tile_x * 3 - 180
    max_lon = min_lon + 3
    min_lat = tile_y * 3 - 90
    max_lat = min_lat + 3
    return min_lon, min_lat, max_lon, max_lat


def get_worldcover_tile_url(tile_x: int, tile_y: int) -> str:
    """URL del tile WorldCover COG en AWS S3."""
    # Formato: ESA_WorldCover_10m_2021_v100_N{lat}E{lon}_Map.tif
    # lat: N/S + 2 dígitos (ej. N36, S03)
    # lon: E/W + 3 dígitos (ej. E003, W012)
    min_lat = tile_y * 3 - 90
    min_lon = tile_x * 3 - 180
    lat_str = f"{'N' if min_lat >= 0 else 'S'}{abs(min_lat):02d}"
    lon_str = f"{'E' if min_lon >= 0 else 'W'}{abs(min_lon):03d}"
    tile_name = f"ESA_WorldCover_10m_2021_v100_{lat_str}{lon_str}_Map.tif"
    return f"{WORLDCOVER_BASE_URL}/{tile_name}"


# ---------------------------------------------------------------------------
# Cliente principal
# ---------------------------------------------------------------------------

class VegetationClient:
    """Cliente unificado ESA WorldCover + IFN3."""

    def __init__(self, cache: VegetationCache | None = None):
        self.cache = cache or VegetationCache()
        self.worldcover_cache_dir = WORLDCOVER_CACHE_DIR
        self.worldcover_cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- WorldCover ----

    def get_worldcover_class(self, lon: float, lat: float, use_cache: bool = True) -> dict:
        """Obtiene clase WorldCover 10m para una coordenada."""
        if use_cache:
            cached = self.cache.get_worldcover(lon, lat)
            if cached:
                return cached

        # Determinar tile
        tile_x, tile_y = lonlat_to_tile(lon, lat)
        tile_url = get_worldcover_tile_url(tile_x, tile_y)

        # Para producción real, aquí se leería el COG con rasterio/rioxarray
        # y se extraería el valor del pixel en (lon, lat).
        # Como demo/placeholder, simulamos basado en ubicación geográfica aproximada.
        # En implementación real:
        # import rasterio
        # with rasterio.open(tile_url) as src:
        #     row, col = src.index(lon, lat)
        #     class_id = src.read(1)[row, col]

        # PLACEHOLDER: clasificar por región biogeográfica aproximada
        class_id = self._estimate_class_by_region(lon, lat)

        result = {
            "class_id": class_id,
            "class_name": WORLDCOVER_CLASSES.get(class_id, "Unknown"),
            "flammability": FLAMMABILITY_WORLDCOVER.get(class_id, 1),
            "tile_url": tile_url,
            "tile_coords": (tile_x, tile_y),
            "source": "WorldCover_2021_v100",
        }

        if use_cache:
            self.cache.set_worldcover(lon, lat, class_id, tile_url)

        return result

    def _estimate_class_by_region(self, lon: float, lat: float) -> int:
        """Estimación aproximada por región (placeholder hasta leer COG real)."""
        # Península Ibérica aproximada
        if -10 <= lon <= 5 and 36 <= lat <= 44:
            # Simplificación: bosque/matorral en montañas, cultivo en llanuras
            # En implementación real, leer del COG
            return 20  # Shrubland como default mediterráneo
        return 10  # Tree cover default

    # ---- IFN3 ----

    def get_ifn3_species(self, lon: float, lat: float, use_cache: bool = True) -> dict:
        """Consulta especies IFN3 en MITECO WMS (GetFeatureInfo)."""
        if use_cache:
            cached = self.cache.get_ifn3(lon, lat)
            if cached:
                return cached

        # Consulta WMS GetFeatureInfo
        # Capas IFN3 principales: "Masa_Forestal", "Especie_Principal", etc.
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetFeatureInfo",
            "FORMAT": "image/png",
            "TRANSPARENT": "true",
            "INFO_FORMAT": "application/json",
            "LAYERS": "Masa_Forestal,Especie_Principal",
            "QUERY_LAYERS": "Masa_Forestal,Especie_Principal",
            "CRS": "EPSG:4326",
            "BBOX": f"{lon-0.001},{lat-0.001},{lon+0.001},{lat+0.001}",
            "WIDTH": 10,
            "HEIGHT": 10,
            "X": 5,
            "Y": 5,
        }

        try:
            response = requests.get(IFN3_WMS_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            species = self._parse_ifn3_response(data)
        except Exception as e:
            print(f"WARNING: IFN3 WMS falló para ({lon}, {lat}): {e}")
            species = []

        # Calcular inflamabilidad
        max_flammability = 1
        dominant = ""
        for sp in species:
            fl = IFN3_SPECIES_FLAMMABILITY.get(sp, 2)
            if fl > max_flammability:
                max_flammability = fl
                dominant = sp

        result = {
            "species_list": species,
            "dominant_species": dominant,
            "max_flammability": max_flammability,
            "source": "MITECO_IFN3_WMS",
        }

        if use_cache and species:
            self.cache.set_ifn3(lon, lat, species, dominant, max_flammability)

        return result

    def _parse_ifn3_response(self, data: dict) -> list[str]:
        """Parsea respuesta GetFeatureInfo de IFN3."""
        species = []
        try:
            features = data.get("features", [])
            for feat in features:
                props = feat.get("properties", {})
                # Buscar campos de especie (varían según servicio)
                for key in ["ESPECIE", "ESPECIE_PR", "ESPECIE_PRINCIPAL", "ESPECIE_DOMINANTE"]:
                    if key in props and props[key]:
                        sp = str(props[key]).strip()
                        if sp and sp not in species:
                            species.append(sp)
        except Exception:
            pass
        return species

    # ---- Combinado ----

    def get_vegetation_profile(self, lon: float, lat: float, use_cache: bool = True) -> dict:
        """Perfil completo de vegetación para una coordenada."""
        wc = self.get_worldcover_class(lon, lat, use_cache)
        ifn3 = self.get_ifn3_species(lon, lat, use_cache)

        # Combinar inflamabilidad: max de ambas fuentes
        combined_flammability = max(wc["flammability"], ifn3.get("max_flammability", 1))

        return {
            "coordinates": {"lon": lon, "lat": lat},
            "worldcover": wc,
            "ifn3": ifn3,
            "combined_flammability": combined_flammability,
            "queried_at": datetime.now(timezone.utc).isoformat(),
        }

    def enrich_cell_day(
        self,
        cell_day_path: Path,
        output_path: Path,
        limit: int | None = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Enriquece cell_day.parquet con perfil de vegetación."""
        cell_day = pd.read_parquet(cell_day_path)
        print(f"Cargados {len(cell_day)} cell-days")

        unique_cells = cell_day.drop_duplicates(subset=["cell_id"])[
            ["cell_id", "cell_centroid_lonlat"]
        ].copy()

        if limit:
            unique_cells = unique_cells.head(limit)

        print(f"Consultando vegetación para {len(unique_cells)} celdas únicas...")

        enriched = []
        for _, row in unique_cells.iterrows():
            cell_id = row["cell_id"]
            centroid = row["cell_centroid_lonlat"]
            if isinstance(centroid, str):
                centroid = json.loads(centroid)
            lon, lat = centroid[0], centroid[1]

            try:
                profile = self.get_vegetation_profile(lon, lat, use_cache)
                profile["cell_id"] = cell_id
                enriched.append(profile)
                print(f"  OK {cell_id}: WC={profile['worldcover']['class_name']}, "
                      f"IFN3={profile['ifn3'].get('dominant_species', 'N/A')}, "
                      f"Flam={profile['combined_flammability']}")
            except Exception as e:
                print(f"  ERROR {cell_id}: {e}")
                enriched.append({"cell_id": cell_id, "error": str(e)})

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from .json_output import JSONArrayWriter
        except ImportError:
            from json_output import JSONArrayWriter

        with JSONArrayWriter(output_path, indent=2) as w:
            for r in enriched:
                w.write(r)

        print(f"Enriquecimiento vegetación completado: {len(enriched)} celdas")
        print(f"Cache stats: {self.cache.stats()}")
        return pd.DataFrame(enriched)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser():
    import argparse
    p = argparse.ArgumentParser(description="Algoritmo VALEN — Cliente Vegetación WorldCover + IFN3")
    p.add_argument("--cell-day", type=Path, help="cell_day.parquet a enriquecer")
    p.add_argument("--output", type=Path, help="JSONL salida enriquecido")
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="Directorio cache")
    p.add_argument("--limit", type=int, help="Limitar celdas para prueba")
    p.add_argument("--no-cache", action="store_true", help="Desactivar cache")
    p.add_argument("--lon", type=float, help="Longitud consulta individual")
    p.add_argument("--lat", type=float, help="Latitud consulta individual")
    return p


def main(argv: list[str] | None = None) -> int:
    import argparse
    args = build_arg_parser().parse_args(argv)

    cache = VegetationCache(args.cache_dir / "vegetation_cache.sqlite")
    client = VegetationClient(cache)

    if args.lon is not None and args.lat is not None:
        result = client.get_vegetation_profile(args.lon, args.lat, not args.no_cache)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if not args.cell_day or not args.output:
        print("ERROR: --cell-day y --output requeridos para enriquecer cell_day")
        return 1

    client.enrich_cell_day(
        args.cell_day,
        args.output,
        limit=args.limit,
        use_cache=not args.no_cache,
    )
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
