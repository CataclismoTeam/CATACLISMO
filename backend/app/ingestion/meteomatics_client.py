#!/usr/bin/env python3
"""
Cliente Meteomatics con cacheo inteligente para Fase 3.

- Autenticación con credenciales hackathon
- Rate limiting: 1000 queries/día
- Cache persistente en SQLite (evita queries repetidos)
- Batch queries por celda-día
- Parámetros clave para riesgo de incendio
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

BASE_URL = "https://api.meteomatics.com"

# Parámetros clave para riesgo de incendio (Meteomatics parameter names)
FIRE_PARAMETERS = [
    "t_2m:C",                    # Temperatura 2m (°C)
    "relative_humidity_2m:p",    # Humedad relativa 2m (%)
    "wind_speed_10m:ms",         # Velocidad viento 10m (m/s)
    "wind_dir_10m:d",            # Dirección viento 10m (grados)
    "wind_gusts_10m_1h:ms",      # Rachas viento 1h (m/s)
    "precip_1h:mm",              # Precipitación 1h (mm)
    "precip_24h:mm",             # Precipitación 24h (mm)
    "global_rad:W/m2",           # Radiación global (W/m²)
    "fire_weather_index:idx",    # Índice meteorológico de incendio (FWI)
    "haines_index:idx",          # Índice Haines (estabilidad atmósfera)
    "fosberg_index:idx",         # Índice Fosberg
    "soil_moisture_0_10cm:m3/m3", # Humedad suelo 0-10cm
    "soil_temp_0_10cm:C",        # Temp suelo 0-10cm
]

# Parámetros derivados útiles
DERIVED_PARAMETERS = [
    "dew_point_2m:C",
    "vapour_pressure_deficit_2m:Pa",
]

ALL_PARAMETERS = FIRE_PARAMETERS + DERIVED_PARAMETERS

DEFAULT_CACHE_DIR = Path(__file__).parent / "cache"
DEFAULT_CACHE_DB = DEFAULT_CACHE_DIR / "meteomatics_cache.sqlite"

# ---------------------------------------------------------------------------
# Cache SQLite
# ---------------------------------------------------------------------------

class MeteomaticsCache:
    """Cache persistente en SQLite para respuestas Meteomatics."""

    def __init__(self, db_path: Path = DEFAULT_CACHE_DB):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queries (
                    cache_key TEXT PRIMARY KEY,
                    param TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_lookup
                ON queries (param, lat, lon, start_date, end_date, interval)
            """)
            conn.commit()

    def _make_key(self, param: str, lat: float, lon: float,
                  start: str, end: str, interval: str) -> str:
        raw = f"{param}|{lat:.6f}|{lon:.6f}|{start}|{end}|{interval}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def get(self, param: str, lat: float, lon: float,
            start: str, end: str, interval: str) -> dict | None:
        key = self._make_key(param, lat, lon, start, end, interval)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT response_json, expires_at FROM queries WHERE cache_key = ?",
                (key,)
            ).fetchone()
            if row:
                if row["expires_at"]:
                    exp = datetime.fromisoformat(row["expires_at"])
                    if datetime.now(timezone.utc) > exp:
                        return None  # expirado
                return json.loads(row["response_json"])
        return None

    def set(self, param: str, lat: float, lon: float,
            start: str, end: str, interval: str,
            response: dict, ttl_hours: int = 24) -> None:
        key = self._make_key(param, lat, lon, start, end, interval)
        expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO queries
                (cache_key, param, lat, lon, start_date, end_date, interval,
                 response_json, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                key, param, lat, lon, start, end, interval,
                json.dumps(response),
                datetime.now(timezone.utc).isoformat(),
                expires
            ))
            conn.commit()

    def stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
            size_mb = self.db_path.stat().st_size / (1024 * 1024)
            return {"entries": total, "size_mb": round(size_mb, 2)}


# ---------------------------------------------------------------------------
# Cliente principal
# ---------------------------------------------------------------------------

class MeteomaticsClient:
    """Cliente Meteomatics con cache y rate limiting."""

    def __init__(
        self,
        username: str,
        password: str,
        cache: MeteomaticsCache | None = None,
        max_queries_per_day: int = 1000,
    ):
        self.username = username
        self.password = password
        self.cache = cache or MeteomaticsCache()
        self.max_queries_per_day = max_queries_per_day
        self._queries_today = 0
        self._day_start = datetime.now(timezone.utc).date()

    def _check_rate_limit(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day_start:
            self._day_start = today
            self._queries_today = 0
        if self._queries_today >= self.max_queries_per_day:
            raise RuntimeError(
                f"Rate limit alcanzado: {self.max_queries_per_day} queries/día. "
                f"Espera hasta medianoche UTC."
            )

    def _make_request(
        self,
        param: str,
        lat: float,
        lon: float,
        start: str,
        end: str,
        interval: str = "PT1H",
        fmt: str = "json",
    ) -> dict:
        """Hace request HTTP a Meteomatics."""
        self._check_rate_limit()

        url = f"{BASE_URL}/{start}--{end}:{interval}/{param}/{lat},{lon}/{fmt}"
        response = requests.get(
            url,
            auth=(self.username, self.password),
            timeout=30,
        )
        self._queries_today += 1

        if response.status_code == 429:
            raise RuntimeError("Rate limit Meteomatics (429). Espera y reintenta.")
        response.raise_for_status()

        if fmt == "json":
            return response.json()
        return {"raw": response.text}

    def query_parameter(
        self,
        param: str,
        lat: float,
        lon: float,
        start: str,
        end: str,
        interval: str = "PT1H",
        use_cache: bool = True,
    ) -> dict:
        """
        Consulta un parámetro para una coordenada y rango temporal.
        Usa cache si está disponible y no expirado.
        """
        # Normalizar fechas a ISO UTC
        if "T" not in start:
            start = f"{start}T00:00:00Z"
        if "T" not in end:
            end = f"{end}T00:00:00Z"

        # Intentar cache
        if use_cache:
            cached = self.cache.get(param, lat, lon, start, end, interval)
            if cached is not None:
                return cached

        # Request real
        data = self._make_request(param, lat, lon, start, end, interval)

        # Guardar en cache
        if use_cache:
            self.cache.set(param, lat, lon, start, end, interval, data)

        return data

    def query_batch(
        self,
        params: list[str],
        lat: float,
        lon: float,
        start: str,
        end: str,
        interval: str = "PT1H",
        use_cache: bool = True,
    ) -> dict[str, dict]:
        """Consulta múltiples parámetros para una coordenada (batch eficiente)."""
        # Meteomatics permite múltiples parámetros separados por coma
        param_str = ",".join(params)
        if use_cache:
            # Verificar cache para cada parámetro individual
            cached_results = {}
            missing = []
            for p in params:
                cached = self.cache.get(p, lat, lon, start, end, interval)
                if cached is not None:
                    cached_results[p] = cached
                else:
                    missing.append(p)
            if not missing:
                return cached_results
            # Consultar solo los que faltan
            results = self._make_request(param_str, lat, lon, start, end, interval)
            # Separar y cachear
            # La respuesta JSON tiene estructura: data[0].coordinates[0].dates[]
            # Para simplificar, guardamos la respuesta completa por cada param
            for p in missing:
                self.cache.set(p, lat, lon, start, end, interval, results)
            return {p: results for p in params}
        else:
            return self._make_request(param_str, lat, lon, start, end, interval)

    def query_cell_day(
        self,
        cell_id: str,
        centroid_lonlat: list[float],
        date_str: str,
        params: list[str] | None = None,
        interval: str = "PT1H",
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """
        Consulta todos los parámetros para una celda-día.
        centroid_lonlat = [lon, lat]
        date_str = 'YYYY-MM-DD'
        """
        if params is None:
            params = ALL_PARAMETERS

        lon, lat = centroid_lonlat
        start = f"{date_str}T00:00:00Z"
        end = f"{date_str}T23:00:00Z"

        # Batch query
        results = self.query_batch(params, lat, lon, start, end, interval, use_cache)

        # Estructurar salida por parámetro con metadatos
        output = {
            "cell_id": cell_id,
            "date": date_str,
            "centroid": {"lon": lon, "lat": lat},
            "parameters": {},
            "queried_at": datetime.now(timezone.utc).isoformat(),
        }

        # La respuesta de Meteomatics batch viene en una estructura única
        # Para simplificar, devolvemos la respuesta cruda por parámetro
        # En uso real, se parsearía cada parámetro de la respuesta JSON
        for p in params:
            output["parameters"][p] = results

        return output

    def get_queries_used_today(self) -> int:
        return self._queries_today

    def get_queries_remaining(self) -> int:
        return max(0, self.max_queries_per_day - self._queries_today)


# ---------------------------------------------------------------------------
# Utilidades de alto nivel para Fase 3
# ---------------------------------------------------------------------------

def enrich_cell_day_with_meteomatics(
    cell_day_path: Path,
    output_path: Path,
    client: MeteomaticsClient,
    params: list[str] | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """
    Enriquece cell_day.parquet con datos Meteomatics.
    Lee cell_day, consulta API para cada (cell_id, date) único,
    y guarda DataFrame enriquecido.
    """
    cell_day = pd.read_parquet(cell_day_path)
    print(f"Cargados {len(cell_day)} cell-days")

    # Deduplicar por cell_id + date (ya vienen separados por sensor,
    # pero meteo es igual para ambos sensors en misma celda-día)
    unique_cells = cell_day.drop_duplicates(subset=["cell_id", "date"])[
        ["cell_id", "date", "cell_centroid_lonlat"]
    ].copy()

    if limit:
        unique_cells = unique_cells.head(limit)

    print(f"Consultando Meteomatics para {len(unique_cells)} celdas-día únicas...")
    print(f"Queries disponibles hoy: {client.get_queries_remaining()}")

    enriched_rows = []

    for _, row in unique_cells.iterrows():
        cell_id = row["cell_id"]
        date_str = str(row["date"])
        centroid = row["cell_centroid_lonlat"]

        if isinstance(centroid, str):
            centroid = json.loads(centroid)
        lon, lat = centroid[0], centroid[1]

        try:
            result = client.query_cell_day(cell_id, [lon, lat], date_str, params)
            enriched_rows.append(result)
            print(f"  OK {cell_id} {date_str} (queries usadas: {client.get_queries_used_today()})")
        except Exception as e:
            print(f"  ERROR {cell_id} {date_str}: {e}")
            enriched_rows.append({
                "cell_id": cell_id,
                "date": date_str,
                "centroid": {"lon": lon, "lat": lat},
                "error": str(e),
            })

    # Guardar resultados
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for r in enriched_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Enriquecimiento completado: {len(enriched_rows)} celdas-día")
    print(f"Queries totales usadas: {client.get_queries_used_today()}")
    print(f"Cache stats: {client.cache.stats()}")

    return pd.DataFrame(enriched_rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    import argparse
    p = argparse.ArgumentParser(description="Cliente Meteomatics para Fase 3")
    p.add_argument("--username", required=True, help="Usuario Meteomatics (hackathon)")
    p.add_argument("--password", required=True, help="Password Meteomatics")
    p.add_argument("--cell-day", type=Path, help="cell_day.parquet a enriquecer")
    p.add_argument("--output", type=Path, help="Archivo JSONL de salida enriquecido")
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="Directorio cache")
    p.add_argument("--limit", type=int, help="Limitar celdas-día para prueba")
    p.add_argument("--params", nargs="+", default=ALL_PARAMETERS, help="Parámetros a consultar")
    p.add_argument("--interval", default="PT1H", help="Intervalo temporal (ISO 8601)")
    p.add_argument("--no-cache", action="store_true", help="Desactivar cache")
    return p


def main(argv: list[str] | None = None) -> int:
    import argparse
    args = build_arg_parser().parse_args(argv)

    if not args.cell_day or not args.output:
        print("ERROR: --cell-day y --output son requeridos para enriquecer")
        return 1

    cache = MeteomaticsCache(args.cache_dir / "meteomatics_cache.sqlite")
    client = MeteomaticsClient(args.username, args.password, cache)

    enrich_cell_day_with_meteomatics(
        args.cell_day,
        args.output,
        client,
        params=args.params,
        limit=args.limit,
    )

    return 0


if __name__ == "__main__":
    import argparse
    import sys
    sys.exit(main())