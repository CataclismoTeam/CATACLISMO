#!/usr/bin/env python3
"""
Cliente histórico de precipitación para Fase 3b: NASA POWER API + ERA5.

- NASA POWER: gratis, sin key, sin límite de queries, histórico 1983-presente
  Resolución 0.5° (~50km), parámetros: precipitación, temp, humedad, viento, radiación
- ERA5 (via Copernicus CDS): 9km/30km, histórico 1979-presente, requiere registro
- CHIRPS: 0.05° (~5km), solo precipitación, 1981-presente
- Cache SQLite persistente
- Cálculo: días desde última lluvia > threshold (ej. 10mm)
- Métricas: precipitación acumulada 7d/30d/90d, días secos consecutivos
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

# NASA POWER API
POWER_BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_PARAMETERS = [
    "PRECTOTCORR",   # Precipitación corregida (mm/day)
    "T2M",           # Temperatura 2m (°C)
    "T2M_MAX",       # Temp máx 2m (°C)
    "T2M_MIN",       # Temp mín 2m (°C)
    "RH2M",          # Humedad relativa 2m (%)
    "WS2M",          # Velocidad viento 2m (m/s)
    "WD2M",          # Dirección viento 2m (°)
    "ALLSKY_SFC_SW_DWN", # Radiación solar superficie (kWh/m2/day)
]

# Thresholds para análisis
RAIN_THRESHOLD_MM = 1.0      # Día de lluvia si >= 1mm
HEAVY_RAIN_THRESHOLD_MM = 10.0  # Lluvia significativa

DEFAULT_CACHE_DIR = Path(__file__).parent / "cache"
DEFAULT_CACHE_DB = DEFAULT_CACHE_DIR / "rainfall_cache.sqlite"

# ---------------------------------------------------------------------------
# Cache SQLite
# ---------------------------------------------------------------------------

class RainfallCache:
    """Cache persistente para datos de precipitación."""

    def __init__(self, db_path: Path = DEFAULT_CACHE_DB):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS power_daily (
                    cache_key TEXT PRIMARY KEY,
                    lon REAL NOT NULL,
                    lat REAL NOT NULL,
                    date TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_power_coord_date
                ON power_daily (lon, lat, date)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rainfall_metrics (
                    cache_key TEXT PRIMARY KEY,
                    lon REAL NOT NULL,
                    lat REAL NOT NULL,
                    reference_date TEXT NOT NULL,
                    days_since_rain_1mm INTEGER,
                    days_since_rain_10mm INTEGER,
                    precip_7d_mm REAL,
                    precip_30d_mm REAL,
                    precip_90d_mm REAL,
                    dry_spell_max_days INTEGER,
                    rain_days_30d INTEGER,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rm_coord_date
                ON rainfall_metrics (lon, lat, reference_date)
            """)
            conn.commit()

    def _make_key(self, lon: float, lat: float, date: str, source: str) -> str:
        raw = f"{source}|{lon:.4f}|{lat:.4f}|{date}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # POWER daily
    def get_power_daily(self, lon: float, lat: float, date: str) -> dict | None:
        key = self._make_key(lon, lat, date, "power")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT params_json FROM power_daily WHERE cache_key = ?",
                (key,)
            ).fetchone()
            if row:
                return json.loads(row["params_json"])
        return None

    def set_power_daily(self, lon: float, lat: float, date: str, params: dict) -> None:
        key = self._make_key(lon, lat, date, "power")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO power_daily
                (cache_key, lon, lat, date, params_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (key, lon, lat, date, json.dumps(params),
                  datetime.now(timezone.utc).isoformat()))
            conn.commit()

    # Rainfall metrics
    def get_metrics(self, lon: float, lat: float, reference_date: str) -> dict | None:
        key = self._make_key(lon, lat, reference_date, "metrics")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT days_since_rain_1mm, days_since_rain_10mm,
                          precip_7d_mm, precip_30d_mm, precip_90d_mm,
                          dry_spell_max_days, rain_days_30d
                   FROM rainfall_metrics WHERE cache_key = ?""",
                (key,)
            ).fetchone()
            if row:
                return dict(row)
        return None

    def set_metrics(self, lon: float, lat: float, reference_date: str, metrics: dict) -> None:
        key = self._make_key(lon, lat, reference_date, "metrics")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO rainfall_metrics
                (cache_key, lon, lat, reference_date,
                 days_since_rain_1mm, days_since_rain_10mm,
                 precip_7d_mm, precip_30d_mm, precip_90d_mm,
                 dry_spell_max_days, rain_days_30d, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                key, lon, lat, reference_date,
                metrics.get("days_since_rain_1mm"),
                metrics.get("days_since_rain_10mm"),
                metrics.get("precip_7d_mm"),
                metrics.get("precip_30d_mm"),
                metrics.get("precip_90d_mm"),
                metrics.get("dry_spell_max_days"),
                metrics.get("rain_days_30d"),
                datetime.now(timezone.utc).isoformat()
            ))
            conn.commit()

    def stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            p = conn.execute("SELECT COUNT(*) FROM power_daily").fetchone()[0]
            m = conn.execute("SELECT COUNT(*) FROM rainfall_metrics").fetchone()[0]
            size_mb = self.db_path.stat().st_size / (1024 * 1024)
            return {"power_entries": p, "metrics_entries": m, "size_mb": round(size_mb, 2)}


# ---------------------------------------------------------------------------
# Cliente NASA POWER
# ---------------------------------------------------------------------------

class RainfallClient:
    """Cliente NASA POWER + cálculo métricas de sequía/lluvia."""

    def __init__(self, cache: RainfallCache | None = None, timeout: int = 30):
        self.cache = cache or RainfallCache()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CATACLISMO/1.0"})

    def _fetch_power_daily(
        self,
        lon: float,
        lat: float,
        start: str,
        end: str,
    ) -> dict:
        """Consulta NASA POWER API para rango de fechas."""
        params = {
            "parameters": ",".join(POWER_PARAMETERS),
            "community": "AG",
            "longitude": lon,
            "latitude": lat,
            "start": start.replace("-", ""),
            "end": end.replace("-", ""),
            "format": "JSON",
        }
        response = self.session.get(POWER_BASE_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_power_daily(
        self,
        lon: float,
        lat: float,
        date: str,
        use_cache: bool = True,
    ) -> dict:
        """Obtiene datos POWER para un día específico."""
        if use_cache:
            cached = self.cache.get_power_daily(lon, lat, date)
            if cached:
                return cached

        # POWER requiere rango, pedimos ese día
        data = self._fetch_power_daily(lon, lat, date, date)

        # Extraer valores del día
        result = {"date": date, "parameters": {}}
        try:
            props = data["properties"]["parameter"]
            for param in POWER_PARAMETERS:
                val = props[param][date.replace("-", "")]
                result["parameters"][param] = val if val != -999 else None
        except (KeyError, TypeError):
            result["parameters"] = {}

        if use_cache:
            self.cache.set_power_daily(lon, lat, date, result)

        return result

    def get_power_range(
        self,
        lon: float,
        lat: float,
        start: str,
        end: str,
        use_cache: bool = True,
    ) -> list[dict]:
        """Obtiene rango de días (más eficiente que día a día)."""
        results = []
        current = start
        while current <= end:
            if use_cache:
                cached = self.cache.get_power_daily(lon, lat, current)
                if cached:
                    results.append(cached)
                    current = (datetime.fromisoformat(current) + timedelta(days=1)).strftime("%Y-%m-%d")
                    continue

            # Fetch en bloques de hasta 365 días (límite POWER)
            block_end = min(end, (datetime.fromisoformat(current) + timedelta(days=300)).strftime("%Y-%m-%d"))
            data = self._fetch_power_daily(lon, lat, current, block_end)

            try:
                props = data["properties"]["parameter"]
                dates_in_range = sorted(set().union(*[set(v.keys()) for v in props.values()]))
                for d in dates_in_range:
                    if d < current.replace("-", "") or d > block_end.replace("-", ""):
                        continue
                    day_str = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                    day_result = {"date": day_str, "parameters": {}}
                    for param in POWER_PARAMETERS:
                        val = props[param].get(d)
                        day_result["parameters"][param] = val if val != -999 else None
                    results.append(day_result)
                    if use_cache:
                        self.cache.set_power_daily(lon, lat, day_str, day_result)
            except (KeyError, TypeError):
                pass

            current = (datetime.fromisoformat(block_end) + timedelta(days=1)).strftime("%Y-%m-%d")

        return results

    def calculate_rainfall_metrics(
        self,
        lon: float,
        lat: float,
        reference_date: str,
        lookback_days: int = 90,
        use_cache: bool = True,
    ) -> dict:
        """Calcula métricas de sequía/lluvia para una fecha de referencia."""
        if use_cache:
            cached = self.cache.get_metrics(lon, lat, reference_date)
            if cached:
                return cached

        ref_dt = datetime.fromisoformat(reference_date)
        start_dt = ref_dt - timedelta(days=lookback_days)
        start_str = start_dt.strftime("%Y-%m-%d")
        ref_str = ref_dt.strftime("%Y-%m-%d")

        # Obtener datos históricos
        daily_data = self.get_power_range(lon, lat, start_str, ref_str, use_cache)

        if not daily_data:
            return {"error": "No data available"}

        # Extraer precipitación diaria
        precip = []
        for day in daily_data:
            p = day.get("parameters", {}).get("PRECTOTCORR")
            precip.append(p if p is not None else 0.0)

        precip = np.array(precip)

        # Métricas
        # Días desde última lluvia >= 1mm
        days_since_1mm = 0
        for p in reversed(precip):
            if p >= RAIN_THRESHOLD_MM:
                break
            days_since_1mm += 1

        # Días desde última lluvia >= 10mm
        days_since_10mm = 0
        for p in reversed(precip):
            if p >= HEAVY_RAIN_THRESHOLD_MM:
                break
            days_since_10mm += 1

        # Precipitación acumulada
        precip_7d = float(np.sum(precip[-7:])) if len(precip) >= 7 else float(np.sum(precip))
        precip_30d = float(np.sum(precip[-30:])) if len(precip) >= 30 else float(np.sum(precip))
        precip_90d = float(np.sum(precip))

        # Máxima racha seca (días consecutivos < 1mm)
        max_dry = 0
        current_dry = 0
        for p in precip:
            if p < RAIN_THRESHOLD_MM:
                current_dry += 1
                max_dry = max(max_dry, current_dry)
            else:
                current_dry = 0

        # Días de lluvia en últimos 30 días
        rain_days_30d = int(np.sum(precip[-30:] >= RAIN_THRESHOLD_MM)) if len(precip) >= 30 else int(np.sum(precip >= RAIN_THRESHOLD_MM))

        metrics = {
            "reference_date": reference_date,
            "days_since_rain_1mm": days_since_1mm,
            "days_since_rain_10mm": days_since_10mm,
            "precip_7d_mm": round(precip_7d, 2),
            "precip_30d_mm": round(precip_30d, 2),
            "precip_90d_mm": round(precip_90d, 2),
            "dry_spell_max_days": int(max_dry),
            "rain_days_30d": rain_days_30d,
            "lookback_days": lookback_days,
        }

        if use_cache:
            self.cache.set_metrics(lon, lat, reference_date, metrics)

        return metrics

    def enrich_cell_day(
        self,
        cell_day_path: Path,
        output_path: Path,
        limit: int | None = None,
        lookback_days: int = 90,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Enriquece cell_day.parquet con métricas de lluvia."""
        cell_day = pd.read_parquet(cell_day_path)
        print(f"Cargados {len(cell_day)} cell-days")

        unique_cells = cell_day.drop_duplicates(subset=["cell_id", "date"])[
            ["cell_id", "date", "cell_centroid_lonlat"]
        ].copy()

        if limit:
            unique_cells = unique_cells.head(limit)

        print(f"Calculando métricas lluvia para {len(unique_cells)} celdas-día...")

        enriched = []
        for _, row in unique_cells.iterrows():
            cell_id = row["cell_id"]
            date_str = str(row["date"])
            centroid = row["cell_centroid_lonlat"]
            if isinstance(centroid, str):
                centroid = json.loads(centroid)
            lon, lat = centroid[0], centroid[1]

            try:
                metrics = self.calculate_rainfall_metrics(lon, lat, date_str, lookback_days, use_cache)
                metrics["cell_id"] = cell_id
                enriched.append(metrics)
                print(f"  OK {cell_id} {date_str}: dry_1mm={metrics['days_since_rain_1mm']}, "
                      f"precip_30d={metrics['precip_30d_mm']}mm, rain_days_30d={metrics['rain_days_30d']}")
            except Exception as e:
                print(f"  ERROR {cell_id} {date_str}: {e}")
                enriched.append({"cell_id": cell_id, "date": date_str, "error": str(e)})

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for r in enriched:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        print(f"Enriquecimiento lluvia completado: {len(enriched)} celdas-día")
        print(f"Cache stats: {self.cache.stats()}")
        return pd.DataFrame(enriched)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser():
    import argparse
    p = argparse.ArgumentParser(description="Cliente Lluvia NASA POWER")
    p.add_argument("--cell-day", type=Path, help="cell_day.parquet a enriquecer")
    p.add_argument("--output", type=Path, help="JSONL salida enriquecido")
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="Directorio cache")
    p.add_argument("--limit", type=int, help="Limitar celdas-día para prueba")
    p.add_argument("--lookback", type=int, default=90, help="Días hacia atrás para métricas")
    p.add_argument("--no-cache", action="store_true", help="Desactivar cache")
    p.add_argument("--lon", type=float, help="Longitud consulta individual")
    p.add_argument("--lat", type=float, help="Latitud consulta individual")
    p.add_argument("--date", type=str, help="Fecha referencia (YYYY-MM-DD)")
    return p


def main(argv: list[str] | None = None) -> int:
    import argparse
    args = build_arg_parser().parse_args(argv)

    cache = RainfallCache(args.cache_dir / "rainfall_cache.sqlite")
    client = RainfallClient(cache)

    if args.lon is not None and args.lat is not None and args.date:
        metrics = client.calculate_rainfall_metrics(
            args.lon, args.lat, args.date, args.lookback, not args.no_cache
        )
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return 0

    if not args.cell_day or not args.output:
        print("ERROR: --cell-day y --output requeridos para enriquecer cell_day")
        return 1

    client.enrich_cell_day(
        args.cell_day,
        args.output,
        limit=args.limit,
        lookback_days=args.lookback,
        use_cache=not args.no_cache,
    )
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())