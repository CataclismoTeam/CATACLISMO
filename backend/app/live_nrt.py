"""live_nrt.py — Ingesta en tiempo casi real (NRT) desde NASA FIRMS + Open-Meteo.

Conecta el secreto `FIRMS_MAP_KEY` (entorno o `.env`) con el pipeline completo:
  NASA FIRMS NRT (últimas 48h en Península Ibérica)
    -> Proyección EPSG:3035 + turnos tácticos 6h (formato VALEN)
    -> Enriquecimiento meteorológico en directo (Open-Meteo)
    -> Predicción CATA (con calibración continua)
    -> Rutas de evacuación LUCIA (con adaptación continua)

Uso desde terminal (`backend/`):
    FIRMS_MAP_KEY=<tu_key> .venv/bin/python -m app.live_nrt --days 2
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.valen.laea import epsg3035_to_lonlat, format_cell_id, lonlat_to_epsg3035

logger = logging.getLogger(__name__)

# BBox Península Ibérica + Baleares (W, S, E, N)
IBERIA_BBOX = "-10.0,35.0,4.5,44.0"
FIRMS_NRT_SOURCES = (
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_CELL_6H_PATH = os.path.join(BASE_DIR, "valen", "output", "cell_6h_live.parquet")
LIVE_METEO_PATH = os.path.join(BASE_DIR, "valen", "output", "cell_day_meteo_live.json")
LIVE_STATUS_PATH = os.path.join(BASE_DIR, "continual", "artifacts", "live_nrt_status.json")


def _get_firms_map_key(explicit_key: str | None = None) -> str:
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()
    env_key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if env_key:
        return env_key
    try:
        from app.config import settings

        return (settings.firms_map_key or "").strip()
    except Exception:
        return ""


def fetch_firms_nrt_csv(
    map_key: str,
    days: int = 2,
    bbox: str = IBERIA_BBOX,
    sources: tuple[str, ...] = FIRMS_NRT_SOURCES,
    timeout_sec: int = 20,
) -> list[dict[str, str]]:
    """Descarga detecciones NRT de NASA FIRMS para la Península Ibérica."""
    rows: list[dict[str, str]] = []
    for src in sources:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/{src}/{bbox}/{int(days)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Cataclismo-NRT/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            if not text.strip() or text.strip().startswith("Invalid"):
                logger.warning("FIRMS NRT (%s) devolvió respuesta inválida/vacía.", src)
                continue
            reader = csv.DictReader(io.StringIO(text))
            for r in reader:
                r["_source"] = src
                rows.append(r)
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo consultar FIRMS NRT (%s): %s", src, exc)
    return rows


def fetch_open_meteo_current(lon: float, lat: float, timeout_sec: int = 10) -> dict[str, float]:
    """Consulta temperatura, humedad y viento actual en Open-Meteo (sin API key)."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}"
        "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation"
        "&wind_speed_unit=ms"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Cataclismo-NRT/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        cur = data.get("current") or {}
        temp = float(cur.get("temperature_2m", 22.0))
        rh = float(cur.get("relative_humidity_2m", 45.0))
        wind = float(cur.get("wind_speed_10m", 4.0))
        fwi_est = float(np.clip(0.6 * max(temp - 10.0, 0.0) + 0.3 * (100.0 - rh) + 1.2 * wind, 0.0, 60.0))
        return {"temperature": temp, "humidity": rh, "wind_speed": wind, "fwi": fwi_est}
    except Exception:
        return {"temperature": 22.0, "humidity": 45.0, "wind_speed": 4.0, "fwi": 20.0}


def build_live_cell_6h_from_firms(raw_rows: list[dict[str, str]]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Convierte filas CSV de NASA FIRMS NRT en `cell_6h` (EPSG:3035) + meteo Open-Meteo."""
    records = []
    for r in raw_rows:
        try:
            lat = float(r["latitude"])
            lon = float(r["longitude"])
            acq_date = str(r["acq_date"]).strip()
            acq_time = str(r.get("acq_time", "1200")).strip().zfill(4)
            hour = int(acq_time[:2]) if acq_time[:2].isdigit() else 12
            slot_h = (hour // 6) * 6
            slot_dt = f"{acq_date} {slot_h:02d}:00"
            x_m, y_m = lonlat_to_epsg3035(lon, lat)
            ix = int(x_m // 1000.0)
            iy = int(y_m // 1000.0)
            cell_id = format_cell_id(iy, ix)
            src = str(r.get("_source", ""))
            sensor = "MODIS" if "MODIS" in src else "VIIRS"
            conf_raw = str(r.get("confidence", "n")).strip().lower()
            conf_rank = 2 if conf_raw in ("h", "high") or (conf_raw.isdigit() and int(conf_raw) >= 80) else 1
            frp = float(r.get("frp") or 0.0)
            scan = float(r.get("scan") or 0.5)
            track = float(r.get("track") or 0.5)
            dn = str(r.get("daynight", "D")).strip().upper()
            records.append(
                {
                    "cell_id": cell_id,
                    "iy": iy,
                    "ix": ix,
                    "slot_dt": slot_dt,
                    "acq_date": acq_date,
                    "sensor": sensor,
                    "platform": str(r.get("satellite", sensor)),
                    "is_day": 1 if dn == "D" else 0,
                    "is_night": 1 if dn == "N" else 0,
                    "is_high_conf": 1 if conf_rank == 2 else 0,
                    "confidence_rank": conf_rank,
                    "frp": frp,
                    "footprint": max(scan, track),
                }
            )
        except Exception:
            continue

    if not records:
        return pd.DataFrame(), []

    df_obs = pd.DataFrame(records)
    grp = df_obs.groupby(["cell_id", "slot_dt", "sensor"], as_index=False).agg(
        iy=("iy", "first"),
        ix=("ix", "first"),
        acq_date=("acq_date", "first"),
        n_obs=("frp", "count"),
        n_day=("is_day", "sum"),
        n_night=("is_night", "sum"),
        n_platforms=("platform", "nunique"),
        n_high_conf=("is_high_conf", "sum"),
        confidence_rank_max=("confidence_rank", "max"),
        frp_sum_mw=("frp", "sum"),
        frp_mean_mw=("frp", "mean"),
        frp_max_mw=("frp", "max"),
        frp_p50_mw=("frp", "median"),
        footprint_max_km=("footprint", "max"),
    )
    grp = grp.rename(columns={"slot_dt": "date"})
    grp["row_id"] = grp["cell_id"] + "|" + grp["date"] + "|" + grp["sensor"]
    grp["level"] = 0
    grp["cell_area_km2"] = 1.0
    grp["product_mix"] = 1.0  # 100% NRT
    dt_ser = pd.to_datetime(grp["acq_date"])
    iso_cal = dt_ser.dt.isocalendar()
    grp["iso_year"] = iso_cal["year"].astype(int)
    grp["iso_week"] = iso_cal["week"].astype(int)
    grp["year_month"] = dt_ser.dt.strftime("%Y-%m")
    grp["sensor_day_observed"] = None
    grp["coverage_fraction"] = None
    grp["flags"] = [[] for _ in range(len(grp))]
    grp["parent_ids"] = [
        {f"L{lvl}": f"ES1K:L{lvl}:Y{int(r.iy) // (2**lvl):05d}:X{int(r.ix) // (2**lvl):05d}" for lvl in (1, 2, 3)}
        for r in grp.itertuples()
    ]
    grp["cell_centroid_lonlat"] = [
        list(epsg3035_to_lonlat((int(r.ix) + 0.5) * 1000.0, (int(r.iy) + 0.5) * 1000.0))
        for r in grp.itertuples()
    ]

    # Enriquecer con meteorología en directo (1 llamada Open-Meteo por bloque 32x32 para no saturar)
    meteo_records: list[dict[str, Any]] = []
    block_weather_cache: dict[tuple[int, int], dict[str, float]] = {}
    for r in grp.itertuples():
        b_key = (int(r.iy) // 32, int(r.ix) // 32)
        if b_key not in block_weather_cache:
            lon_c, lat_c = r.cell_centroid_lonlat
            block_weather_cache[b_key] = fetch_open_meteo_current(lon_c, lat_c)
        w = block_weather_cache[b_key]
        meteo_records.append({"cell_id": r.cell_id, "date": r.acq_date, **w})

    grp = grp.drop(columns=["iy", "ix", "acq_date"])
    return grp, meteo_records


def run_live_nrt_cycle(
    map_key: str | None = None,
    days: int = 2,
    max_zones: int = 8,
) -> dict[str, Any]:
    """Ejecuta un ciclo completo en directo: FIRMS NRT -> VALEN 6h -> CATA -> LUCIA."""
    resolved_key = _get_firms_map_key(map_key)
    if not resolved_key:
        raise RuntimeError("Falta FIRMS_MAP_KEY en variables de entorno o backend/.env.")

    raw_rows = fetch_firms_nrt_csv(resolved_key, days=days)
    now_iso = datetime.now(timezone.utc).isoformat()
    if not raw_rows:
        status = {
            "status": "no_active_fires_in_iberia",
            "checked_at": now_iso,
            "firms_detections": 0,
            "message": "Sin detecciones térmicas activas en la Península Ibérica en las últimas horas.",
        }
        os.makedirs(os.path.dirname(LIVE_STATUS_PATH), exist_ok=True)
        with open(LIVE_STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
        return status

    df_6h, meteo_records = build_live_cell_6h_from_firms(raw_rows)
    if df_6h.empty:
        return {"status": "no_valid_cells", "checked_at": now_iso, "firms_detections": len(raw_rows)}

    os.makedirs(os.path.dirname(LIVE_CELL_6H_PATH), exist_ok=True)
    df_6h.to_parquet(LIVE_CELL_6H_PATH, index=False)
    with open(LIVE_METEO_PATH, "w", encoding="utf-8") as f:
        json.dump(meteo_records, f)

    # Ejecutar CATA y LUCIA sobre la ventana en directo
    from app.cata import config as cata_config
    from app.cata.model import export_cata_predictions_for_lucia, extract_model_config, load_fire_model
    from app.cata.train import load_contract_cell_day
    from app.lucia import config as lucia_config
    from app.lucia.router import generate_lucia_geojson_from_cata

    latest_slot = str(df_6h["date"].max())
    model_cata = load_fire_model(cata_config.DEFAULT_MODEL_PATH, compile_model_flag=False)
    cfg = extract_model_config(model_cata)
    x_tr, y_tr, x_va, y_va, meta_tr, meta_va = load_contract_cell_day(
        LIVE_CELL_6H_PATH,
        grid_size=cfg.height,
        time_steps=cfg.time_steps,
        num_channels=cfg.num_channels,
        meteo_path=LIVE_METEO_PATH,
        return_patch_meta=True,
        target_date=latest_slot,
    )
    all_x = np.concatenate([x_tr, x_va], axis=0) if len(x_tr) and len(x_va) else (x_tr if len(x_tr) else x_va)
    all_y = np.concatenate([y_tr, y_va], axis=0) if len(y_tr) and len(y_va) else (y_tr if len(y_tr) else y_va)
    all_meta = (meta_tr + meta_va) if (meta_tr or meta_va) else []

    if len(all_x) == 0:
        return {"status": "insufficient_live_window", "checked_at": now_iso, "firms_detections": len(raw_rows)}

    scores_act = all_x[:, -1, :, :, 0].sum(axis=(1, 2))
    top_idx = np.argsort(scores_act)[::-1][: min(len(all_x), max_zones)]
    export_cata_predictions_for_lucia(
        model=model_cata,
        sequence=all_x[top_idx],
        output_path=cata_config.DEFAULT_PREDICTIONS_PATH,
        patch_origins=[all_meta[int(i)] for i in top_idx] if all_meta else None,
        y_true_batch=all_y[top_idx] if len(all_y) == len(all_x) else None,
    )

    lucia_geojson = generate_lucia_geojson_from_cata(
        cata_predictions_path=cata_config.DEFAULT_PREDICTIONS_PATH,
        output_geojson_path=lucia_config.DEFAULT_GEOJSON_OUTPUT_PATH,
        model_path=lucia_config.DEFAULT_MODEL_PATH,
    )

    status = {
        "status": "updated_live",
        "checked_at": now_iso,
        "latest_slot": latest_slot,
        "firms_detections": len(raw_rows),
        "live_cell_6h_rows": len(df_6h),
        "zones_predicted": lucia_geojson["metadata"]["total_zones_processed"],
        "routes_generated": lucia_geojson["metadata"]["total_routes_generated"],
    }
    os.makedirs(os.path.dirname(LIVE_STATUS_PATH), exist_ok=True)
    with open(LIVE_STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    return status


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    p = argparse.ArgumentParser(description="Ingesta Near Real-Time (NASA FIRMS + Open-Meteo -> CATA -> LUCIA)")
    p.add_argument("--days", type=int, default=2, help="Días NRT hacia atrás (1..10, defecto 2)")
    p.add_argument("--max-zones", type=int, default=8)
    args = p.parse_args()
    res = run_live_nrt_cycle(days=args.days, max_zones=args.max_zones)
    logger.info("Resultado NRT live: %s", res)


if __name__ == "__main__":
    main()
