"""
train.py — Pipeline de entrenamiento e inferencia del algoritmo CATA (ConvLSTM),
integrado con el algoritmo de validación y enriquecimiento de datos VALEN
y con salida de predicciones estructurada para el futuro algoritmo LUCIA
(cálculo de vías de escape de personas y animales).

Entradas desde VALEN (`backend/app/valen/output/`):
  1. `cell_day` (`cell_day.parquet` / `cell_day.json`): 13 canales térmicos MODIS/VIIRS.
  2. `meteo` (`cell_day_meteo.json`): 4 canales meteorológicos (FWI, viento, humedad, temperatura).
  3. `rainfall` (`cell_day_rainfall.json`): 3 canales de sequía y precipitación acumulada.
  4. `vegetation` (`cell_day_vegetation.json`): inflamabilidad del combustible (WorldCover + IFN3).
  5. `validated_cell_day` (`validated_cell_day.json` / `.parquet`): filtrado de ruido (`decision != RECHAZA`)
     y score global de confianza `valen_score`.

Salida de predicciones de CATA para LUCIA:
  - Archivo JSON (`artifacts/predictions/cata_predictions.json` o `--predictions-output`)
    con cuadrículas diferenciadas (`SAFE`, `PREDICTED_FIRE`, `CONFIRMED_BURNED`, `CONFIRMED_AND_CONTINUES`),
    tiempos estimados de llegada del fuego y costes de tránsito para personas y animales.

Modos:
  scratch   Entrena un modelo CATA nuevo con C canales (por defecto C=22 con todo VALEN).
  finetune  Carga un checkpoint (.keras/.h5) y continúa entrenando sus pesos.
  expand    Channel surgery sobre un checkpoint (C_old -> C_new) + entrenamiento en 2 fases.
  predict   Carga un modelo CATA y datos de VALEN (o sintéticos) y exporta predicciones para LUCIA.
  demo      Smoke test end-to-end: scratch(C=1) -> finetune -> expand(C=22) -> exporta predicciones para LUCIA.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import gc
import json
import logging
import os
import re
import time

import keras
import numpy as np
import tensorflow as tf

# ===========================================================================
# Configuración de Épocas Virtuales, Checkpoints y Smoke Test (DRY_RUN)
# ===========================================================================
DRY_RUN: bool = False
STEPS_PER_EPOCH: int = 500
VALIDATION_STEPS: int = 100
CHECKPOINTS_DIR: str = "checkpoints"

try:
    from . import config
    from .config import ModelConfig
    from .model import (
        cata_predict_quadrants,
        compile_model,
        create_model,
        expand_model_channels,
        export_cata_predictions_for_lucia,
        extract_model_config,
        load_fire_model,
        set_expansion_warmup,
    )
except ImportError:
    import config
    from config import ModelConfig
    from model import (
        cata_predict_quadrants,
        compile_model,
        create_model,
        expand_model_channels,
        export_cata_predictions_for_lucia,
        extract_model_config,
        load_fire_model,
        set_expansion_warmup,
    )

logger = logging.getLogger("fire_train")

# 8-vecindad para difusión isotrópica en la rejilla de 1000x1000m
_NEIGHBORS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
_CELL_ID_RE = re.compile(r"^ES(?:1K|5K):L(\d+):Y(-?\d+):X(-?\d+)$")


def _shift(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """out[i, j] = a[i - dy, j - dx] con relleno a cero (sin wrap-around)."""
    h, w = a.shape
    out = np.zeros_like(a)
    out[max(dy, 0) : h + min(dy, 0), max(dx, 0) : w + min(dx, 0)] = a[
        max(-dy, 0) : h + min(-dy, 0), max(-dx, 0) : w + min(-dx, 0)
    ]
    return out


# ===========================================================================
# 1. Utilidades del contrato de datos y normalización de canales VALEN -> CATA
# ===========================================================================
def parse_cell_id(cell_id: str) -> tuple[int, int, int]:
    """Parsea `ES1K:L{level}:Y{iy}:X{ix}` (o `ES5K:...`) -> (level, iy, ix)."""
    m = _CELL_ID_RE.match(str(cell_id).strip())
    if not m:
        raise ValueError(f"cell_id inválido según contrato ES1K/ES5K: {cell_id!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def format_cell_id(
    iy: int,
    ix: int,
    level: int = config.GRID_LEVEL,
    prefix: str = config.CELL_PREFIX,
) -> str:
    """Formatea coordenadas de cuadrícula de 1000x1000m a `ES1K:L{level}:Y{iy}:X{ix}`."""
    return f"{prefix}:L{level}:Y{iy}:X{ix}"


def normalize_contract_channels(raw: dict[str, np.ndarray], num_channels: int) -> np.ndarray:
    """Convierte las métricas crudas de VALEN (`cell_day` + `meteo` + `rainfall` + `vegetation`) a [0, 1].

    `raw` contiene arrays de igual shape `(..., H, W)` con:
      - Bloque 1 (`cell_day`): frp_sum_mw, frp_max_mw, frp_mean_mw, frp_p50_mw,
        n_obs, n_high_conf, confidence_rank_max, n_day, n_night, footprint_max_km,
        n_platforms, product_mix, n_obs_viirs.
      - Bloque 2 (`meteo`): meteo_fwi (o fwi 0..50), meteo_wind_speed (o wind_speed_ms 0..20),
        meteo_humidity_inv (o humidity_pct 10..90), meteo_temp (o temp_c -5..45).
      - Bloque 3 (`rainfall`): rain_days_since_1mm (0..30), rain_dry_spell_max (0..30),
        rain_precip_30d_inv (o precip_30d_mm 0..100).
      - Bloque 4 (`vegetation` + `valen`): veg_flammability (o combined_flammability 1..5),
        valen_score (0..1).

    Devuelve tensor `(..., H, W, num_channels)` alineado con `config.CHANNEL_REGISTRY`.
    """
    frp_scale = config.FRP_LOG1P_SCALE
    obs_scale = config.OBS_LOG1P_SCALE

    n_obs_raw = np.maximum(raw["n_obs"], 0.0)
    n_obs_denom = np.maximum(n_obs_raw, 1.0)
    active = (n_obs_raw > 0).astype(np.float32)
    zeros = np.zeros_like(n_obs_raw, dtype=np.float32)

    # Meteo: acepta tanto valores ya normalizados [0,1] como magnitudes físicas crudas
    if "meteo_fwi" in raw:
        meteo_fwi = np.clip(raw["meteo_fwi"], 0.0, 1.0)
    elif "fwi" in raw:
        meteo_fwi = np.clip(raw["fwi"] / config.FWI_MAX_SCALE, 0.0, 1.0)
    else:
        meteo_fwi = zeros

    if "meteo_wind_speed" in raw:
        meteo_wind = np.clip(raw["meteo_wind_speed"], 0.0, 1.0)
    elif "wind_speed_ms" in raw:
        meteo_wind = np.clip(raw["wind_speed_ms"] / config.WIND_SPEED_MAX_MS, 0.0, 1.0)
    else:
        meteo_wind = zeros

    if "meteo_humidity_inv" in raw:
        meteo_hum_inv = np.clip(raw["meteo_humidity_inv"], 0.0, 1.0)
    elif "humidity_pct" in raw:
        meteo_hum_inv = np.clip(
            1.0
            - (raw["humidity_pct"] - config.HUMIDITY_MIN_PCT)
            / (config.HUMIDITY_MAX_PCT - config.HUMIDITY_MIN_PCT),
            0.0,
            1.0,
        )
    else:
        meteo_hum_inv = zeros

    if "meteo_temp" in raw:
        meteo_temp = np.clip(raw["meteo_temp"], 0.0, 1.0)
    elif "temp_c" in raw:
        meteo_temp = np.clip(
            (raw["temp_c"] - config.TEMP_MIN_C) / (config.TEMP_MAX_C - config.TEMP_MIN_C),
            0.0,
            1.0,
        )
    else:
        meteo_temp = zeros

    # Rainfall / Sequía
    if "rain_days_since_1mm" in raw:
        rain_dsr = np.clip(raw["rain_days_since_1mm"], 0.0, 1.0)
    elif "days_since_rain_1mm" in raw:
        rain_dsr = np.clip(raw["days_since_rain_1mm"] / config.RAIN_DAYS_MAX_SCALE, 0.0, 1.0)
    else:
        rain_dsr = zeros

    if "rain_dry_spell_max" in raw:
        rain_dsm = np.clip(raw["rain_dry_spell_max"], 0.0, 1.0)
    elif "dry_spell_max_days" in raw:
        rain_dsm = np.clip(raw["dry_spell_max_days"] / config.RAIN_DAYS_MAX_SCALE, 0.0, 1.0)
    else:
        rain_dsm = zeros

    if "rain_precip_30d_inv" in raw:
        rain_p30_inv = np.clip(raw["rain_precip_30d_inv"], 0.0, 1.0)
    elif "precip_30d_mm" in raw:
        rain_p30_inv = np.clip(1.0 - raw["precip_30d_mm"] / config.PRECIP_30D_MAX_MM, 0.0, 1.0)
    else:
        rain_p30_inv = zeros

    # Vegetation & VALEN score
    if "veg_flammability" in raw:
        veg_flam = np.clip(raw["veg_flammability"], 0.0, 1.0)
    elif "combined_flammability" in raw:
        veg_flam = np.clip(
            (raw["combined_flammability"] - config.VEG_FLAMMABILITY_MIN)
            / (config.VEG_FLAMMABILITY_MAX - config.VEG_FLAMMABILITY_MIN),
            0.0,
            1.0,
        )
    else:
        veg_flam = zeros

    valen_score = np.clip(raw.get("valen_score", active * 0.5), 0.0, 1.0)

    computed: dict[str, np.ndarray] = {
        # Bloque 1: Cell Day (0..12)
        "frp_sum_mw": np.clip(np.log1p(np.maximum(raw["frp_sum_mw"], 0.0)) / frp_scale, 0.0, 1.0),
        "frp_max_mw": np.clip(np.log1p(np.maximum(raw["frp_max_mw"], 0.0)) / frp_scale, 0.0, 1.0),
        "frp_mean_mw": np.clip(
            np.log1p(np.maximum(raw["frp_mean_mw"], 0.0)) / frp_scale, 0.0, 1.0
        ),
        "frp_p50_mw": np.clip(np.log1p(np.maximum(raw["frp_p50_mw"], 0.0)) / frp_scale, 0.0, 1.0),
        "n_obs": np.clip(np.log1p(n_obs_raw) / obs_scale, 0.0, 1.0),
        "n_high_conf": np.clip(np.log1p(np.maximum(raw["n_high_conf"], 0.0)) / obs_scale, 0.0, 1.0),
        "confidence_rank_max": np.clip(raw["confidence_rank_max"] / 2.0, 0.0, 1.0) * active,
        "n_day_ratio": np.clip(raw["n_day"] / n_obs_denom, 0.0, 1.0) * active,
        "n_night_ratio": np.clip(raw["n_night"] / n_obs_denom, 0.0, 1.0) * active,
        "footprint_max_km": np.clip(raw["footprint_max_km"] / 5.0, 0.0, 1.0) * active,
        "n_platforms": np.clip(raw["n_platforms"] / 3.0, 0.0, 1.0) * active,
        "product_mix": np.clip(raw["product_mix"], 0.0, 1.0) * active,
        "viirs_obs_share": (
            np.clip(raw.get("n_obs_viirs", n_obs_raw * 0.65) / n_obs_denom, 0.0, 1.0) * active
        ),
        # Bloque 2: Meteo de VALEN (13..16)
        "meteo_fwi": meteo_fwi,
        "meteo_wind_speed": meteo_wind,
        "meteo_humidity_inv": meteo_hum_inv,
        "meteo_temp": meteo_temp,
        # Bloque 3: Rainfall de VALEN (17..19)
        "rain_days_since_1mm": rain_dsr,
        "rain_dry_spell_max": rain_dsm,
        "rain_precip_30d_inv": rain_p30_inv,
        # Bloque 4: Vegetation & VALEN score (20..21)
        "veg_flammability": veg_flam,
        "valen_score": valen_score,
    }

    names = config.CHANNEL_REGISTRY[:num_channels]
    return np.stack([computed[k].astype(np.float32) for k in names], axis=-1)


# ===========================================================================
# 2. Lector e integración de los datos de VALEN (Cell Day + Meteo + Rainfall + Veg)
# ===========================================================================
def _read_json_or_jsonl_records(path: str) -> list[dict]:
    """Lee un archivo JSON (array) o JSONL y devuelve lista de dicts."""
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return [json.loads(line) for line in content.splitlines() if line.strip()]


def _resolve_valen_paths(
    primary_path: str,
    meteo_path: str | None = None,
    rainfall_path: str | None = None,
    vegetation_path: str | None = None,
    validated_path: str | None = None,
) -> dict[str, str | None]:
    """Descubre automáticamente los 5 archivos de VALEN a partir de una carpeta o ruta base."""
    if os.path.isdir(primary_path):
        base_dir = primary_path
        cd_6h = os.path.join(base_dir, "cell_6h.parquet")
        cd_parquet = os.path.join(base_dir, "cell_day.parquet")
        cd_json = os.path.join(base_dir, "cell_day.json")
        if os.path.exists(cd_6h):
            cell_day_file = cd_6h
        elif os.path.exists(cd_parquet):
            cell_day_file = cd_parquet
        else:
            cell_day_file = cd_json
    else:
        base_dir = os.path.dirname(os.path.abspath(primary_path))
        fname = os.path.basename(primary_path)
        if fname.startswith("validated_cell_day"):
            validated_path = validated_path or primary_path
            cd_6h = os.path.join(base_dir, "cell_6h.parquet")
            cd_parquet = os.path.join(base_dir, "cell_day.parquet")
            cd_json = os.path.join(base_dir, "cell_day.json")
            cell_day_file = (
                cd_6h
                if os.path.exists(cd_6h)
                else (
                    cd_parquet
                    if os.path.exists(cd_parquet)
                    else (cd_json if os.path.exists(cd_json) else primary_path)
                )
            )
        else:
            cell_day_file = primary_path

    def _auto(explicit: str | None, candidates: Sequence[str]) -> str | None:
        if explicit and os.path.exists(explicit):
            return explicit
        for c in candidates:
            p = os.path.join(base_dir, c)
            if os.path.exists(p):
                return p
        return None

    return {
        "cell_day": cell_day_file,
        "meteo": _auto(meteo_path, ("cell_day_meteo.json", "cell_day_meteo.jsonl")),
        "rainfall": _auto(rainfall_path, ("cell_day_rainfall.json", "cell_day_rainfall.jsonl")),
        "vegetation": _auto(
            vegetation_path, ("cell_day_vegetation.json", "cell_day_vegetation.jsonl")
        ),
        "validated": _auto(
            validated_path, ("validated_cell_day.parquet", "validated_cell_day.json")
        ),
    }


def _enrich_cell_day_with_valen(
    df,
    meteo_path: str | None = None,
    rainfall_path: str | None = None,
    vegetation_path: str | None = None,
    validated_path: str | None = None,
    include_rejected: bool = False,
):
    """Enriquece `cell_day` con Meteo, Rainfall, Vegetation y Validación de VALEN."""
    import pandas as pd

    df = df.copy()

    # 1. Validación de VALEN (`validated_cell_day`): score, decision y features pre-normalizadas
    val_lookup: dict[tuple[str, str, str], dict] = {}
    val_cell_date_lookup: dict[tuple[str, str], dict] = {}
    if validated_path and os.path.exists(validated_path):
        if validated_path.endswith(".parquet"):
            val_records = pd.read_parquet(validated_path).to_dict(orient="records")
        else:
            val_records = _read_json_or_jsonl_records(validated_path)
        for r in val_records:
            cid = str(r.get("cell_id", ""))
            dt = str(r.get("date", ""))
            sen = str(r.get("sensor", ""))
            val_lookup[(cid, dt, sen)] = r
            val_cell_date_lookup[(cid, dt)] = r

    # Si `df` era directamente `validated_cell_day` sin métricas FRP, aseguramos columnas base
    if "n_obs" not in df.columns:
        df["n_obs"] = 1
        df["n_day"] = 1
        df["n_night"] = 0
        df["n_platforms"] = 1
        df["n_high_conf"] = 0
        df["confidence_rank_max"] = 1
        df["frp_sum_mw"] = 5.0
        df["frp_mean_mw"] = 5.0
        df["frp_max_mw"] = 5.0
        df["frp_p50_mw"] = 5.0
        df["footprint_max_km"] = 0.5
        df["product_mix"] = 0.0

    # Filtrado por decisión de VALEN (descarta ruido "RECHAZA" salvo que se pida incluirlo)
    decisions = []
    scores = []
    val_feats = []
    for _, row in df.iterrows():
        dt_day = str(row.get("date", ""))[:10]
        key3 = (str(row.get("cell_id", "")), dt_day, str(row.get("sensor", "")))
        key2 = (str(row.get("cell_id", "")), dt_day)
        vr = val_lookup.get(key3) or val_cell_date_lookup.get(key2) or {}
        dec = row.get("decision") if "decision" in row and pd.notna(row.get("decision")) else vr.get("decision", "ACEPTA")
        sc = row.get("score") if "score" in row and pd.notna(row.get("score")) else vr.get("score", 0.5)
        feats = row.get("features") if "features" in row and isinstance(row.get("features"), dict) else (vr.get("features") or {})
        decisions.append(str(dec))
        scores.append(float(sc) if sc is not None else 0.5)
        val_feats.append(feats if isinstance(feats, dict) else {})

    df["valen_decision"] = decisions
    df["valen_score"] = scores
    df["_valen_features"] = val_feats

    if not include_rejected and val_lookup:
        kept = df[df["valen_decision"].isin(config.VALEN_ACCEPTED_DECISIONS)]
        if len(kept) > 0:
            logger.info(
                "Filtro VALEN aplicado: %d/%d registros aceptados/revisables (descartados %d RECHAZA)",
                len(kept),
                len(df),
                len(df) - len(kept),
            )
            df = kept.copy()

    # 2. Vegetación de VALEN (`cell_day_vegetation.json`): inflamabilidad combinada 1..5
    veg_by_cell: dict[str, float] = {}
    if vegetation_path and os.path.exists(vegetation_path):
        for r in _read_json_or_jsonl_records(vegetation_path):
            cid = str(r.get("cell_id", ""))
            flam = r.get("combined_flammability")
            if flam is None and isinstance(r.get("worldcover"), dict):
                flam = r["worldcover"].get("flammability")
            if cid and flam is not None:
                veg_by_cell[cid] = float(
                    np.clip(
                        (float(flam) - config.VEG_FLAMMABILITY_MIN)
                        / (config.VEG_FLAMMABILITY_MAX - config.VEG_FLAMMABILITY_MIN),
                        0.0,
                        1.0,
                    )
                )

    # 3. Rainfall / Sequía de VALEN (`cell_day_rainfall.json`)
    rain_by_cell_date: dict[tuple[str, str], dict[str, float]] = {}
    rain_by_cell: dict[str, dict[str, float]] = {}
    if rainfall_path and os.path.exists(rainfall_path):
        for r in _read_json_or_jsonl_records(rainfall_path):
            cid = str(r.get("cell_id", ""))
            dt = str(r.get("reference_date") or r.get("date") or "")
            if not cid:
                continue
            dsr = r.get("days_since_rain_1mm")
            dsm = r.get("dry_spell_max_days")
            p30 = r.get("precip_30d_mm")
            norm_rain = {
                "rain_days_since_1mm": (
                    float(np.clip(float(dsr) / config.RAIN_DAYS_MAX_SCALE, 0.0, 1.0))
                    if dsr is not None
                    else None
                ),
                "rain_dry_spell_max": (
                    float(np.clip(float(dsm) / config.RAIN_DAYS_MAX_SCALE, 0.0, 1.0))
                    if dsm is not None
                    else None
                ),
                "rain_precip_30d_inv": (
                    float(np.clip(1.0 - float(p30) / config.PRECIP_30D_MAX_MM, 0.0, 1.0))
                    if p30 is not None
                    else None
                ),
            }
            rain_by_cell[cid] = norm_rain
            if dt:
                rain_by_cell_date[(cid, dt)] = norm_rain

    # 4. Meteorología de VALEN (`cell_day_meteo.json`)
    meteo_by_cell_date: dict[tuple[str, str], dict[str, float]] = {}
    meteo_by_cell: dict[str, dict[str, float]] = {}
    if meteo_path and os.path.exists(meteo_path):
        for r in _read_json_or_jsonl_records(meteo_path):
            cid = str(r.get("cell_id", ""))
            dt = str(r.get("date", ""))
            if not cid or "error" in r:
                continue
            params = r.get("parameters") or {}

            def _extract_param(p_key: str, flat_key: str) -> float | None:
                if flat_key in r and r[flat_key] is not None:
                    return float(r[flat_key])
                p_obj = params.get(p_key)
                if isinstance(p_obj, dict):
                    dates_list = p_obj.get("dates") or []
                    vals = [d.get("value") for d in dates_list if isinstance(d, dict) and d.get("value") is not None]
                    if vals:
                        return float(np.mean(vals))
                return None

            fwi_v = _extract_param("fire_weather_index:idx", "fwi")
            wind_v = _extract_param("wind_speed_10m:ms", "wind_speed")
            hum_v = _extract_param("relative_humidity_2m:p", "humidity")
            temp_v = _extract_param("t_2m:C", "temperature")

            norm_m = {
                "meteo_fwi": (
                    float(np.clip(fwi_v / config.FWI_MAX_SCALE, 0.0, 1.0))
                    if fwi_v is not None
                    else None
                ),
                "meteo_wind_speed": (
                    float(np.clip(wind_v / config.WIND_SPEED_MAX_MS, 0.0, 1.0))
                    if wind_v is not None
                    else None
                ),
                "meteo_humidity_inv": (
                    float(
                        np.clip(
                            1.0
                            - (hum_v - config.HUMIDITY_MIN_PCT)
                            / (config.HUMIDITY_MAX_PCT - config.HUMIDITY_MIN_PCT),
                            0.0,
                            1.0,
                        )
                    )
                    if hum_v is not None
                    else None
                ),
                "meteo_temp": (
                    float(
                        np.clip(
                            (temp_v - config.TEMP_MIN_C) / (config.TEMP_MAX_C - config.TEMP_MIN_C),
                            0.0,
                            1.0,
                        )
                    )
                    if temp_v is not None
                    else None
                ),
            }
            meteo_by_cell[cid] = norm_m
            if dt:
                meteo_by_cell_date[(cid, dt)] = norm_m

    # Ensamblar columnas normalizadas [0, 1] para cada fila con fallback a `validated_cell_day.features`
    col_fwi, col_wind, col_hum, col_temp = [], [], [], []
    col_dsr, col_dsm, col_p30, col_veg = [], [], [], []

    for _, row in df.iterrows():
        cid = str(row.get("cell_id", ""))
        dt_raw = str(row.get("date", ""))
        dt = dt_raw[:10]
        slot_h = int(dt_raw[11:13]) if len(dt_raw) >= 13 and dt_raw[11:13].isdigit() else None
        vf = row["_valen_features"]

        m_info = meteo_by_cell_date.get((cid, dt)) or meteo_by_cell.get(cid) or {}
        r_info = rain_by_cell_date.get((cid, dt)) or rain_by_cell.get(cid) or {}

        fwi_val = m_info.get("meteo_fwi")
        if fwi_val is None:
            fwi_val = float(vf.get("fwi", 0.0))

        wind_val = m_info.get("meteo_wind_speed")
        if wind_val is None:
            wind_val = float(vf.get("wind_speed", 0.0))

        hum_val = m_info.get("meteo_humidity_inv")
        if hum_val is None:
            hum_val = float(vf.get("humidity", 0.0))

        temp_val = m_info.get("meteo_temp")
        if temp_val is None:
            temp_val = float(np.clip(0.5 * fwi_val + 0.5 * hum_val, 0.0, 1.0))

        # Modulación diurna por turno táctico de 6h (00=Madrugada, 06=Mañana, 12=Tarde 30-30-30, 18=Noche)
        if slot_h is not None:
            if slot_h < 6:
                temp_val = float(np.clip(temp_val * 0.82, 0.0, 1.0))
                hum_val = float(np.clip(hum_val * 0.80, 0.0, 1.0))
                wind_val = float(np.clip(wind_val * 0.88, 0.0, 1.0))
                fwi_val = float(np.clip(fwi_val * 0.85, 0.0, 1.0))
            elif slot_h < 12:
                temp_val = float(np.clip(temp_val * 0.95, 0.0, 1.0))
                hum_val = float(np.clip(hum_val * 0.94, 0.0, 1.0))
                wind_val = float(np.clip(wind_val * 0.96, 0.0, 1.0))
                fwi_val = float(np.clip(fwi_val * 0.95, 0.0, 1.0))
            elif slot_h < 18:
                temp_val = float(np.clip(temp_val * 1.15, 0.0, 1.0))
                hum_val = float(np.clip(hum_val * 1.15, 0.0, 1.0))
                wind_val = float(np.clip(wind_val * 1.12, 0.0, 1.0))
                fwi_val = float(np.clip(fwi_val * 1.12, 0.0, 1.0))
            else:
                temp_val = float(np.clip(temp_val * 0.92, 0.0, 1.0))
                hum_val = float(np.clip(hum_val * 0.90, 0.0, 1.0))
                wind_val = float(np.clip(wind_val * 0.95, 0.0, 1.0))
                fwi_val = float(np.clip(fwi_val * 0.92, 0.0, 1.0))

        dsr_val = r_info.get("rain_days_since_1mm")
        if dsr_val is None:
            dsr_val = float(vf.get("days_since_rain_1mm", 0.0))

        dsm_val = r_info.get("rain_dry_spell_max")
        if dsm_val is None:
            dsm_val = float(vf.get("dry_spell_max", dsr_val))

        p30_val = r_info.get("rain_precip_30d_inv")
        if p30_val is None:
            p30_val = float(vf.get("precip_30d", 0.0))

        veg_val = veg_by_cell.get(cid)
        if veg_val is None:
            veg_val = float(vf.get("vegetation_flammability", 0.75))

        col_fwi.append(fwi_val)
        col_wind.append(wind_val)
        col_hum.append(hum_val)
        col_temp.append(temp_val)
        col_dsr.append(dsr_val)
        col_dsm.append(dsm_val)
        col_p30.append(p30_val)
        col_veg.append(veg_val)

    df["meteo_fwi"] = np.asarray(col_fwi, dtype=np.float32)
    df["meteo_wind_speed"] = np.asarray(col_wind, dtype=np.float32)
    df["meteo_humidity_inv"] = np.asarray(col_hum, dtype=np.float32)
    df["meteo_temp"] = np.asarray(col_temp, dtype=np.float32)
    df["rain_days_since_1mm"] = np.asarray(col_dsr, dtype=np.float32)
    df["rain_dry_spell_max"] = np.asarray(col_dsm, dtype=np.float32)
    df["rain_precip_30d_inv"] = np.asarray(col_p30, dtype=np.float32)
    df["veg_flammability"] = np.asarray(col_veg, dtype=np.float32)
    return df.drop(columns=["_valen_features"], errors="ignore")


def load_contract_cell_day(
    path: str,
    grid_size: int = config.GRID_SIZE,
    time_steps: int = config.TIME_STEPS,
    num_channels: int = config.NUM_CHANNELS,
    invalid_periods: Sequence[str] = ("2026-09",),
    val_split: float = config.VALIDATION_SPLIT,
    seed: int = config.SEED,
    meteo_path: str | None = None,
    rainfall_path: str | None = None,
    vegetation_path: str | None = None,
    validated_path: str | None = None,
    include_rejected: bool = False,
    return_patch_meta: bool = False,
    target_date: str | None = None,
):
    """Carga y cruza los artefactos de VALEN (`cell_day`, `meteo`, `rainfall`, `vegetation`, `validated`)."""
    import pandas as pd

    resolved = _resolve_valen_paths(
        path,
        meteo_path=meteo_path,
        rainfall_path=rainfall_path,
        vegetation_path=vegetation_path,
        validated_path=validated_path,
    )
    cd_path = resolved["cell_day"]
    if not cd_path or not os.path.exists(cd_path):
        raise FileNotFoundError(f"No se encontró archivo cell_day en: {path}")

    if cd_path.endswith(".parquet"):
        df = pd.read_parquet(cd_path)
    elif cd_path.endswith(".jsonl") or cd_path.endswith(".json"):
        df = pd.DataFrame(_read_json_or_jsonl_records(cd_path))
    else:
        raise ValueError(f"Formato no soportado: {cd_path} (use carpeta VALEN, .parquet, .json, .csv.gz o .npz)")

    is_subdaily = len(df) > 0 and " " in str(df["date"].iloc[0])
    step_hours = getattr(config, "STEP_HOURS", 6) if is_subdaily else 24

    if target_date:
        target_str = str(target_date).strip()
        if is_subdaily and len(target_str) == 10:
            # Si se pasa solo YYYY-MM-DD en modo 6h, elegir el último turno con actividad de ese día (o 12:00 UTC)
            day_matches = df[df["date"].astype(str).str.startswith(target_str)]["date"].astype(str)
            target_str = str(day_matches.max()) if len(day_matches) > 0 else f"{target_str} 12:00"
        dt_target = pd.Timestamp(target_str)
        dt_start = (
            dt_target - pd.Timedelta(hours=time_steps * step_hours)
            if is_subdaily
            else dt_target - pd.Timedelta(days=time_steps)
        )
        df_dates = pd.to_datetime(df["date"], errors="coerce")
        df = df[(df_dates >= dt_start) & (df_dates <= dt_target)].copy()
        if df.empty:
            raise ValueError(
                f"No hay datos de VALEN en el rango [{dt_start} .. {dt_target}]"
            )
        target_date = target_str

    df = _enrich_cell_day_with_valen(
        df,
        meteo_path=resolved["meteo"],
        rainfall_path=resolved["rainfall"],
        vegetation_path=resolved["vegetation"],
        validated_path=resolved["validated"],
        include_rejected=include_rejected,
    )

    return _build_patches_from_cell_day_df(
        df,
        grid_size=grid_size,
        time_steps=time_steps,
        num_channels=num_channels,
        invalid_periods=invalid_periods,
        val_split=val_split,
        seed=seed,
        return_patch_meta=return_patch_meta,
        target_date=target_date,
    )


def _build_patches_from_cell_day_df(
    df,
    grid_size: int,
    time_steps: int,
    num_channels: int,
    invalid_periods: Sequence[str],
    val_split: float,
    seed: int,
    return_patch_meta: bool = False,
    max_patches: int = 2500,
    target_date: str | None = None,
):
    import pandas as pd

    if "level" in df.columns:
        df = df[df["level"] == config.GRID_LEVEL]
    if "year_month" in df.columns and invalid_periods:
        df = df[~df["year_month"].isin(invalid_periods)]
    if "flags" in df.columns:

        def _keep_flags(fl):
            if fl is None or (isinstance(fl, float) and np.isnan(fl)):
                return True
            s = set(fl) if isinstance(fl, (list, tuple, np.ndarray)) else set()
            return "partial_period" not in s and "island_domain" not in s

        df_filtered = df[df["flags"].map(_keep_flags)]
        if len(df_filtered) > 0:
            df = df_filtered

    parsed = df["cell_id"].map(parse_cell_id)
    df = df.copy()
    df["iy"] = [p[1] for p in parsed]
    df["ix"] = [p[2] for p in parsed]
    df["date"] = df["date"].astype(str)
    df["n_obs_viirs"] = np.where(df.get("sensor", "VIIRS") == "VIIRS", df["n_obs"], 0)
    df["w_frp_mean"] = df["frp_mean_mw"] * df["n_obs"]
    df["w_frp_p50"] = df["frp_p50_mw"] * df["n_obs"]
    df["w_pmix"] = df["product_mix"] * df["n_obs"]

    for valen_col, default_val in (
        ("meteo_fwi", 0.0),
        ("meteo_wind_speed", 0.0),
        ("meteo_humidity_inv", 0.0),
        ("meteo_temp", 0.0),
        ("rain_days_since_1mm", 0.0),
        ("rain_dry_spell_max", 0.0),
        ("rain_precip_30d_inv", 0.0),
        ("veg_flammability", 0.75),
        ("valen_score", 0.5),
    ):
        if valen_col not in df.columns:
            df[valen_col] = default_val

    # Mapa de centroides WGS84 por celda (iy, ix) para exportar a LUCIA
    centroids_by_cell: dict[tuple[int, int], list[float]] = {}
    if "cell_centroid_lonlat" in df.columns:
        for _, r in df[["iy", "ix", "cell_centroid_lonlat"]].drop_duplicates(subset=["iy", "ix"]).iterrows():
            c_lonlat = r["cell_centroid_lonlat"]
            if isinstance(c_lonlat, (list, tuple, np.ndarray)) and len(c_lonlat) >= 2:
                centroids_by_cell[(int(r["iy"]), int(r["ix"]))] = [
                    round(float(c_lonlat[0]), 6),
                    round(float(c_lonlat[1]), 6),
                ]

    grouped = df.groupby(["iy", "ix", "date"], as_index=False).agg(
        frp_sum_mw=("frp_sum_mw", "sum"),
        frp_max_mw=("frp_max_mw", "max"),
        w_frp_mean=("w_frp_mean", "sum"),
        w_frp_p50=("w_frp_p50", "sum"),
        n_obs=("n_obs", "sum"),
        n_high_conf=("n_high_conf", "sum"),
        confidence_rank_max=("confidence_rank_max", "max"),
        n_day=("n_day", "sum"),
        n_night=("n_night", "sum"),
        footprint_max_km=("footprint_max_km", "max"),
        n_platforms=("n_platforms", "sum"),
        w_pmix=("w_pmix", "sum"),
        n_obs_viirs=("n_obs_viirs", "sum"),
        meteo_fwi=("meteo_fwi", "max"),
        meteo_wind_speed=("meteo_wind_speed", "max"),
        meteo_humidity_inv=("meteo_humidity_inv", "max"),
        meteo_temp=("meteo_temp", "max"),
        rain_days_since_1mm=("rain_days_since_1mm", "max"),
        rain_dry_spell_max=("rain_dry_spell_max", "max"),
        rain_precip_30d_inv=("rain_precip_30d_inv", "max"),
        veg_flammability=("veg_flammability", "max"),
        valen_score=("valen_score", "max"),
    )
    denom = np.maximum(grouped["n_obs"].to_numpy(np.float32), 1.0)
    grouped["frp_mean_mw"] = grouped["w_frp_mean"] / denom
    grouped["frp_p50_mw"] = grouped["w_frp_p50"] / denom
    grouped["product_mix"] = grouped["w_pmix"] / denom

    is_subdaily = len(grouped) > 0 and " " in str(grouped["date"].iloc[0])
    step_hours = getattr(config, "STEP_HOURS", 6) if is_subdaily else 24
    freq_str = f"{step_hours}h" if is_subdaily else "D"
    fmt_str = "%Y-%m-%d %H:00" if is_subdaily else "%Y-%m-%d"

    if target_date:
        dt_target = pd.Timestamp(target_date)
        dt_min = (
            dt_target - pd.Timedelta(hours=time_steps * step_hours)
            if is_subdaily
            else dt_target - pd.Timedelta(days=time_steps)
        )
        date_min = dt_min.strftime(fmt_str)
        date_max = dt_target.strftime(fmt_str)
    else:
        date_min = grouped["date"].min()
        date_max = grouped["date"].max()
    dates = pd.date_range(date_min, date_max, freq=freq_str).strftime(fmt_str)
    date_to_idx = {d: i for i, d in enumerate(dates)}
    n_days = len(dates)
    if n_days <= time_steps:
        raise ValueError(f"Serie temporal insuficiente ({n_days} días) para time_steps={time_steps}")

    # Partición espacial por bloques de celdas (evita fuga entre train y val, §6)
    unique_cells = grouped[["iy", "ix"]].drop_duplicates().to_numpy()
    rng = np.random.default_rng(seed)
    block_ids = [f"{iy // (grid_size // 2)}_{ix // (grid_size // 2)}" for iy, ix in unique_cells]
    unique_blocks = sorted(set(block_ids))
    rng.shuffle(unique_blocks)
    n_val_blocks = max(1, int(len(unique_blocks) * val_split))
    val_blocks = set(unique_blocks[:n_val_blocks])

    raw_keys = [
        "frp_sum_mw",
        "frp_max_mw",
        "frp_mean_mw",
        "frp_p50_mw",
        "n_obs",
        "n_high_conf",
        "confidence_rank_max",
        "n_day",
        "n_night",
        "footprint_max_km",
        "n_platforms",
        "product_mix",
        "n_obs_viirs",
        "meteo_fwi",
        "meteo_wind_speed",
        "meteo_humidity_inv",
        "meteo_temp",
        "rain_days_since_1mm",
        "rain_dry_spell_max",
        "rain_precip_30d_inv",
        "veg_flammability",
        "valen_score",
    ]

    x_tr, y_tr, x_va, y_va = [], [], [], []
    score_tr, score_va = [], []
    meta_tr, meta_va = [], []
    half = grid_size // 2
    max_s = n_days - time_steps - 1
    max_val = max(1, int(max_patches * val_split)) if max_patches > 0 else 0
    max_tr = max(1, max_patches - max_val) if max_patches > 0 else 0

    def _prune_lists(x_list, y_list, scores, metas, cap: int):
        if cap <= 0 or len(x_list) <= cap:
            return x_list, y_list, scores, metas
        order = np.argsort(scores)[::-1]
        n_top = int(cap * 0.7)
        top_idx = order[:n_top]
        rest_idx = order[n_top:]
        n_rest = cap - n_top
        rest_sample = (
            rng.choice(rest_idx, size=n_rest, replace=False)
            if n_rest > 0 and len(rest_idx) >= n_rest
            else rest_idx[:n_rest]
        )
        keep_idx = np.sort(np.concatenate([top_idx, rest_sample]))
        new_x = [x_list[i] for i in keep_idx]
        new_y = [y_list[i] for i in keep_idx]
        new_s = [scores[i] for i in keep_idx]
        new_m = [metas[i] for i in keep_idx]
        del x_list, y_list, scores, metas
        gc.collect()
        return new_x, new_y, new_s, new_m

    for b_id in unique_blocks:
        by, bx = (int(v) for v in b_id.split("_"))
        cy, cx = by * half + half // 2, bx * half + half // 2
        y0, x0 = cy - half, cx - half
        sub = grouped[
            (grouped["iy"] >= y0)
            & (grouped["iy"] < y0 + grid_size)
            & (grouped["ix"] >= x0)
            & (grouped["ix"] < x0 + grid_size)
        ]
        if sub.empty:
            continue

        ti = sub["date"].map(date_to_idx).to_numpy(dtype=np.int64)
        obs_arr = sub["n_obs"].to_numpy(dtype=np.float32)
        active_ti = np.unique(ti[obs_arr > 0])
        if len(active_ti) == 0:
            continue

        # En modo táctico 6h, incluir el turno intermedio cuando hay confirmación satelital en t-1 y t+1 (12h VIIRS)
        if is_subdaily and len(active_ti) > 1:
            bridged_ti = set(int(t) for t in active_ti)
            for idx_a in range(len(active_ti) - 1):
                if int(active_ti[idx_a + 1]) - int(active_ti[idx_a]) == 2:
                    bridged_ti.add(int(active_ti[idx_a]) + 1)
            active_ti = np.array(sorted(bridged_ti), dtype=np.int64)

        # Identificar únicamente los índices temporales s con actividad en [s, s + time_steps]
        active_starts_set: set[int] = set()
        for t_act in active_ti:
            s_lo = max(0, int(t_act) - time_steps)
            s_hi = min(max_s, int(t_act))
            for s_idx in range(s_lo, s_hi + 1):
                active_starts_set.add(s_idx)
        if not active_starts_set:
            continue

        active_starts = sorted(active_starts_set)
        needed_t = sorted({t for s in active_starts for t in range(s, s + time_steps + 1)})
        t_global_to_local = {t_g: t_l for t_l, t_g in enumerate(needed_t)}
        n_local = len(needed_t)

        # Alocar raw_cube solo sobre los días activos necesarios (en vez de los ~2100 días globales)
        raw_cube = {k: np.zeros((n_local, grid_size, grid_size), np.float32) for k in raw_keys}
        for _, v_row in sub[["iy", "ix", "veg_flammability"]].drop_duplicates(subset=["iy", "ix"]).iterrows():
            vy = int(v_row["iy"]) - y0
            vx = int(v_row["ix"]) - x0
            raw_cube["veg_flammability"][:, vy, vx] = float(v_row["veg_flammability"])

        sub_mask = np.isin(ti, needed_t)
        if not np.any(sub_mask):
            del raw_cube
            continue
        sub_active = sub.iloc[sub_mask]
        ti_local = np.array([t_global_to_local[int(t)] for t in ti[sub_mask]], dtype=np.int64)
        yi = (sub_active["iy"] - y0).to_numpy()
        xi = (sub_active["ix"] - x0).to_numpy()
        for k in raw_keys:
            raw_cube[k][ti_local, yi, xi] = sub_active[k].to_numpy(np.float32)

        # Puente de persistencia orbital 6h (evita falsos negativos en turnos MODIS-Terra sin añadir falsos positivos)
        if is_subdaily and n_local >= 3:
            def _pool3x3(arr2d: np.ndarray) -> np.ndarray:
                p = np.pad(arr2d, 1, mode="edge")
                return np.maximum.reduce([
                    p[0:-2, 0:-2], p[0:-2, 1:-1], p[0:-2, 2:],
                    p[1:-1, 0:-2], p[1:-1, 1:-1], p[1:-1, 2:],
                    p[2:,   0:-2], p[2:,   1:-1], p[2:,   2:],
                ])

            for l_t in range(1, n_local - 1):
                if needed_t[l_t] - needed_t[l_t - 1] != 1 or needed_t[l_t + 1] - needed_t[l_t] != 1:
                    continue
                obs_prev = raw_cube["n_obs"][l_t - 1]
                obs_curr = raw_cube["n_obs"][l_t]
                obs_next = raw_cube["n_obs"][l_t + 1]
                if not np.any(obs_prev > 0) or not np.any(obs_next > 0):
                    continue
                bridge_mask = (obs_curr == 0) & (
                    ((obs_prev > 0) & (_pool3x3(obs_next) > 0))
                    | ((_pool3x3(obs_prev) > 0) & (obs_next > 0))
                )
                if not np.any(bridge_mask):
                    continue
                for k in raw_keys:
                    if k == "veg_flammability":
                        continue
                    v_interp = 0.85 * 0.5 * (
                        _pool3x3(raw_cube[k][l_t - 1])[bridge_mask]
                        + _pool3x3(raw_cube[k][l_t + 1])[bridge_mask]
                    )
                    raw_cube[k][l_t][bridge_mask] = v_interp
                raw_cube["n_obs"][l_t][bridge_mask] = np.maximum(
                    raw_cube["n_obs"][l_t][bridge_mask], 1.0
                )

        features = normalize_contract_channels(raw_cube, num_channels)
        # Target: actividad térmica validada en t+1 (n_obs > 0)
        burning = (raw_cube["n_obs"] > 0).astype(np.float32)

        block_centroids = {
            (iy, ix): lonlat
            for (iy, ix), lonlat in centroids_by_cell.items()
            if y0 <= iy < y0 + grid_size and x0 <= ix < x0 + grid_size
        }

        is_val = b_id in val_blocks
        for s in active_starts:
            l_start = t_global_to_local[s]
            l_end = l_start + time_steps
            # Copias explícitas para no retener el array padre `features` / `burning` en memoria
            win_x = features[l_start:l_end].copy()
            win_y = burning[l_end][..., None].copy()
            act_score = float(win_x[..., 0].sum() + 2.0 * win_y.sum())
            if act_score <= 0.0:
                continue
            patch_info = {
                "zone_id": f"ES1K_block_{b_id}_{dates[s + time_steps - 1]}",
                "y0": int(y0),
                "x0": int(x0),
                "reference_date": str(dates[s + time_steps - 1]),
                "predicted_date": str(dates[s + time_steps]),
                "centroids": block_centroids,
            }
            if is_val:
                x_va.append(win_x)
                y_va.append(win_y)
                score_va.append(act_score)
                meta_va.append(patch_info)
            else:
                x_tr.append(win_x)
                y_tr.append(win_y)
                score_tr.append(act_score)
                meta_tr.append(patch_info)

        del raw_cube, features, burning
        # Poda incremental dentro del bucle para que x_tr/x_va nunca excedan ~1.2x del límite en RAM
        if max_tr > 0 and len(x_tr) > int(max_tr * 1.2):
            x_tr, y_tr, score_tr, meta_tr = _prune_lists(x_tr, y_tr, score_tr, meta_tr, max_tr)
        if max_val > 0 and len(x_va) > int(max_val * 1.2):
            x_va, y_va, score_va, meta_va = _prune_lists(x_va, y_va, score_va, meta_va, max_val)
        gc.collect()

    def _cap_and_pack(x_list, y_list, scores, metas, cap: int):
        x_list, y_list, scores, metas = _prune_lists(x_list, y_list, scores, metas, cap)
        n_out = len(x_list)
        if n_out == 0:
            return (
                np.empty((0, time_steps, grid_size, grid_size, num_channels), dtype=np.float32),
                np.empty((0, grid_size, grid_size, 1), dtype=np.float32),
                metas,
            )
        # Pre-alocar buffer con np.empty y liberar cada elemento al copiar para no duplicar RAM
        x_buf = np.empty((n_out, time_steps, grid_size, grid_size, num_channels), dtype=np.float32)
        y_buf = np.empty((n_out, grid_size, grid_size, 1), dtype=np.float32)
        for i in range(n_out):
            x_buf[i] = x_list[i]
            y_buf[i] = y_list[i]
            x_list[i] = None
            y_list[i] = None
        del x_list, y_list, scores
        gc.collect()
        return x_buf, y_buf, metas

    x_tr_arr, y_tr_arr, meta_tr = _cap_and_pack(x_tr, y_tr, score_tr, meta_tr, max_tr)
    x_va_arr, y_va_arr, meta_va = _cap_and_pack(x_va, y_va, score_va, meta_va, max_val)

    if return_patch_meta:
        return x_tr_arr, y_tr_arr, x_va_arr, y_va_arr, meta_tr, meta_va

    return x_tr_arr, y_tr_arr, x_va_arr, y_va_arr


# ===========================================================================
# 3. Generador sintético de los 22 canales VALEN -> CATA
# ===========================================================================
class SyntheticContractGenerator:
    """Simula la evolución de incendios con las 22 variables de VALEN:
    Cell Day (MODIS/VIIRS) + Meteo + Rainfall + Vegetation + Score de validación.
    """

    def __init__(
        self,
        grid_size: int = config.GRID_SIZE,
        time_steps: int = config.TIME_STEPS,
        num_channels: int = config.NUM_CHANNELS,
        seed: int = config.SEED,
        base_spread: float = 0.24,
        observation_dropout: float = 0.06,
    ):
        if not 1 <= num_channels <= len(config.CHANNEL_REGISTRY):
            raise ValueError(f"num_channels fuera de rango: {num_channels}")
        self.n = grid_size
        self.t = time_steps
        self.c = num_channels
        self.rng = np.random.default_rng(seed)
        self.base_spread = base_spread
        self.observation_dropout = observation_dropout
        yy, xx = np.mgrid[0:grid_size, 0:grid_size] / grid_size
        self._yy, self._xx = yy.astype(np.float32), xx.astype(np.float32)

    def _susceptibility_field(self) -> np.ndarray:
        """Campo continuo de inflamabilidad vegetal y sequía base en celdas L0."""
        f = np.zeros((self.n, self.n), np.float32)
        for _ in range(5):
            fx, fy = self.rng.uniform(-2.5, 2.5, 2)
            phase = self.rng.uniform(0, 2 * np.pi)
            f += self.rng.uniform(0.4, 1.0) * np.cos(
                2 * np.pi * (fx * self._xx + fy * self._yy) + phase
            )
        f -= f.min()
        f = f / (f.max() + 1e-8)
        return np.clip(f * 1.15 - 0.05, 0.0, 1.0).astype(np.float32)

    def simulate_episode(self, n_steps: int) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """Simula `n_steps` días de la grilla con Cell Day + Meteo + Rainfall + Vegetation.

        Devuelve `(raw_channels_dict, true_burning_mask)`.
        """
        n = self.n
        suscept = self._susceptibility_field()
        veg_flam = np.clip(suscept + self.rng.normal(0, 0.06, (n, n)), 0.0, 1.0).astype(np.float32)
        rain_dsr_base = np.clip(
            0.35 + 0.55 * suscept + self.rng.normal(0, 0.08, (n, n)), 0.0, 1.0
        ).astype(np.float32)
        rain_dsm_base = np.clip(
            np.maximum(rain_dsr_base, rain_dsr_base + self.rng.uniform(0.0, 0.2, (n, n))), 0.0, 1.0
        ).astype(np.float32)
        rain_p30_inv_base = np.clip(
            0.4 + 0.5 * rain_dsr_base + self.rng.normal(0, 0.07, (n, n)), 0.0, 1.0
        ).astype(np.float32)

        duration = (2 + np.round(4 * suscept)).astype(np.int32)

        age = np.full((n, n), -1, np.int32)  # -1: inactivo; >=0: días ardiendo
        candidates = np.argwhere(suscept > 0.45)
        if len(candidates) == 0:
            candidates = np.argwhere(suscept >= 0)
        n_ign = min(len(candidates), int(self.rng.integers(1, 4)))
        for idx in self.rng.choice(len(candidates), size=n_ign, replace=False):
            age[tuple(candidates[idx])] = 0

        raw_keys = [
            "frp_sum_mw",
            "frp_max_mw",
            "frp_mean_mw",
            "frp_p50_mw",
            "n_obs",
            "n_high_conf",
            "confidence_rank_max",
            "n_day",
            "n_night",
            "footprint_max_km",
            "n_platforms",
            "product_mix",
            "n_obs_viirs",
            "meteo_fwi",
            "meteo_wind_speed",
            "meteo_humidity_inv",
            "meteo_temp",
            "rain_days_since_1mm",
            "rain_dry_spell_max",
            "rain_precip_30d_inv",
            "veg_flammability",
            "valen_score",
        ]
        raw = {k: np.zeros((n_steps, n, n), np.float32) for k in raw_keys}
        burning_hist = np.zeros((n_steps, n, n), np.float32)

        for step in range(n_steps):
            burning = (age >= 0) & (age < duration)
            burning_hist[step] = burning.astype(np.float32)

            # Variables meteorológicas diarias (Meteo de VALEN)
            wind_day = np.clip(
                self.rng.uniform(0.2, 0.75) + self.rng.normal(0, 0.08, (n, n)), 0.0, 1.0
            ).astype(np.float32)
            hum_inv_day = np.clip(
                0.35 + 0.45 * suscept + self.rng.normal(0, 0.08, (n, n)), 0.0, 1.0
            ).astype(np.float32)
            temp_day = np.clip(
                0.45 + 0.35 * hum_inv_day + self.rng.normal(0, 0.06, (n, n)), 0.0, 1.0
            ).astype(np.float32)
            fwi_day = np.clip(
                0.40 * wind_day + 0.35 * hum_inv_day + 0.25 * rain_dsr_base, 0.0, 1.0
            ).astype(np.float32)

            vigor = np.where(
                burning,
                (0.35 + 0.65 * suscept) * (1.0 - (age / np.maximum(duration, 1)) * 0.45),
                0.0,
            ).astype(np.float32)

            observed = burning & (self.rng.random((n, n)) > self.observation_dropout)

            n_obs = np.where(
                observed,
                np.maximum(1, np.round(np.expm1(vigor * 3.8 + self.rng.normal(0, 0.25, (n, n))))),
                0.0,
            ).astype(np.float32)

            viirs_share = np.clip(self.rng.normal(0.68, 0.15, (n, n)), 0.0, 1.0).astype(np.float32)
            n_obs_viirs = np.round(n_obs * viirs_share)

            frp_mean = np.where(
                observed,
                np.maximum(1.5, np.expm1(vigor * 4.2 + self.rng.normal(0, 0.2, (n, n)))),
                0.0,
            ).astype(np.float32)
            frp_sum = (n_obs * frp_mean).astype(np.float32)
            frp_max = np.where(
                observed,
                frp_mean
                * np.clip(
                    1.0 + 0.45 * np.log1p(n_obs) + self.rng.uniform(0, 0.4, (n, n)),
                    1.0,
                    4.5,
                ),
                0.0,
            ).astype(np.float32)
            frp_p50 = (
                frp_mean * np.clip(self.rng.normal(0.82, 0.08, (n, n)), 0.5, 1.0)
            ).astype(np.float32)

            high_frac = np.clip(0.2 + 0.65 * vigor + self.rng.normal(0, 0.1, (n, n)), 0.0, 1.0)
            n_high = np.minimum(n_obs, np.round(n_obs * high_frac)).astype(np.float32)
            conf_rank = np.where(
                ~observed, 0.0, np.where(n_high > 0, 2.0, np.where(vigor > 0.25, 1.0, 0.0))
            ).astype(np.float32)

            night_frac = np.clip(0.3 + 0.5 * vigor + self.rng.normal(0, 0.12, (n, n)), 0.0, 1.0)
            n_night = np.round(n_obs * night_frac).astype(np.float32)
            n_day = np.maximum(0.0, n_obs - n_night).astype(np.float32)

            footprint = np.where(
                observed,
                np.clip(
                    0.5 + (1.0 - viirs_share) * 2.2 + 0.9 * vigor + self.rng.uniform(0, 0.6, (n, n)),
                    0.37,
                    4.8,
                ),
                0.0,
            ).astype(np.float32)
            n_plat = np.where(
                observed, np.clip(1.0 + np.floor(np.log1p(n_obs) * 0.8), 1.0, 3.0), 0.0
            ).astype(np.float32)
            pmix = np.where(
                observed, np.clip(self.rng.beta(1.2, 3.0, (n, n)), 0.0, 1.0), 0.0
            ).astype(np.float32)

            valen_sc = np.where(
                observed,
                np.clip(
                    0.30 * (conf_rank / 2.0)
                    + 0.25 * fwi_day
                    + 0.20 * veg_flam
                    + 0.15 * rain_dsr_base
                    + 0.10 * (n_plat / 3.0),
                    0.35,
                    1.0,
                ),
                0.0,
            ).astype(np.float32)

            raw["frp_sum_mw"][step] = frp_sum
            raw["frp_max_mw"][step] = frp_max
            raw["frp_mean_mw"][step] = frp_mean
            raw["frp_p50_mw"][step] = frp_p50
            raw["n_obs"][step] = n_obs
            raw["n_high_conf"][step] = n_high
            raw["confidence_rank_max"][step] = conf_rank
            raw["n_day"][step] = n_day
            raw["n_night"][step] = n_night
            raw["footprint_max_km"][step] = footprint
            raw["n_platforms"][step] = n_plat
            raw["product_mix"][step] = pmix
            raw["n_obs_viirs"][step] = n_obs_viirs
            raw["meteo_fwi"][step] = fwi_day
            raw["meteo_wind_speed"][step] = wind_day
            raw["meteo_humidity_inv"][step] = hum_inv_day
            raw["meteo_temp"][step] = temp_day
            raw["rain_days_since_1mm"][step] = np.clip(rain_dsr_base + step * 0.01, 0.0, 1.0)
            raw["rain_dry_spell_max"][step] = rain_dsm_base
            raw["rain_precip_30d_inv"][step] = rain_p30_inv_base
            raw["veg_flammability"][step] = veg_flam
            raw["valen_score"][step] = valen_sc

            spread_power = vigor * (
                0.45
                + 0.20 * fwi_day
                + 0.15 * wind_day
                + 0.10 * (n_high / np.maximum(n_obs, 1.0))
                + 0.10 * (n_night / np.maximum(n_obs, 1.0))
            )
            no_ignite = np.ones((n, n), np.float32)
            for dy, dx in _NEIGHBORS:
                dist = np.hypot(dy, dx)
                src = _shift(spread_power, dy, dx)
                p = (self.base_spread / dist) * src
                no_ignite *= 1.0 - np.clip(p, 0.0, 1.0)
            p_ignite = (1.0 - no_ignite) * (0.6 * veg_flam + 0.4 * rain_dsr_base)
            new_fire = (age < 0) & (self.rng.random((n, n)) < p_ignite)

            age = np.where(age >= 0, age + 1, age)
            age[new_fire] = 0

        return raw, burning_hist

    def generate(self, n_samples: int) -> tuple[np.ndarray, np.ndarray]:
        """X: (N, T, H, W, C) float32; Y: (N, H, W, 1) máscara de fuego en t+1."""
        x_arr = np.empty((n_samples, self.t, self.n, self.n, self.c), np.float32)
        y_arr = np.empty((n_samples, self.n, self.n, 1), np.float32)
        i = 0
        while i < n_samples:
            ep_len = self.t + 1 + config.SYNTH_EPISODE_EXTRA_STEPS
            raw, burning = self.simulate_episode(ep_len)
            stacked = normalize_contract_channels(raw, self.c)  # (L, H, W, C)
            for s in range(0, ep_len - self.t, 2):
                if i >= n_samples:
                    break
                target = burning[s + self.t]
                if target.sum() == 0 and self.rng.random() < 0.8:
                    continue
                x_arr[i] = stacked[s : s + self.t]
                y_arr[i, ..., 0] = target
                i += 1
        return x_arr, y_arr


# Alias de compatibilidad hacia atrás
SyntheticFireGenerator = SyntheticContractGenerator


# ===========================================================================
# 4. Datos -> tf.data
# ===========================================================================
def load_npz_dataset(path: str) -> tuple[np.ndarray, np.ndarray]:
    with np.load(path) as d:
        x_arr, y_arr = d["X"].astype(np.float32), d["Y"].astype(np.float32)
    if y_arr.ndim == 3:
        y_arr = y_arr[..., None]
    return x_arr, y_arr


def _arrays_to_ds(
    x_arr: np.ndarray,
    y_arr: np.ndarray,
    batch_size: int,
    shuffle: bool,
    seed: int,
) -> tf.data.Dataset:
    ds = tf.data.Dataset.from_tensor_slices((x_arr, y_arr))
    if shuffle:
        ds = ds.shuffle(len(x_arr), seed=seed, reshuffle_each_iteration=True)
    return ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)


def make_datasets(
    x_arr: np.ndarray,
    y_arr: np.ndarray,
    batch_size: int = config.BATCH_SIZE,
    val_split: float = config.VALIDATION_SPLIT,
    seed: int = config.SEED,
) -> tuple[tf.data.Dataset, tf.data.Dataset]:
    if len(x_arr) != len(y_arr):
        raise ValueError("X e Y tienen distinto número de muestras")
    idx = np.random.default_rng(seed).permutation(len(x_arr))
    n_val = max(1, int(len(x_arr) * val_split))
    val_idx, tr_idx = idx[:n_val], idx[n_val:]
    return (
        _arrays_to_ds(x_arr[tr_idx], y_arr[tr_idx], batch_size, True, seed),
        _arrays_to_ds(x_arr[val_idx], y_arr[val_idx], batch_size, False, seed),
    )


def get_data(args, num_channels: int, grid: int, time_steps: int, seed_offset: int = 0):
    """Carga datos de VALEN (Cell Day + Meteo + Rainfall + Vegetation), .npz o sintéticos."""
    seed = args.seed + seed_offset
    if args.data:
        if args.data.endswith(".npz"):
            x_arr, y_arr = load_npz_dataset(args.data)
            x_arr = x_arr[..., :num_channels]
            expected = (time_steps, grid, grid, num_channels)
            if x_arr.shape[1:] != expected:
                raise ValueError(f"Datos {x_arr.shape[1:]} incompatibles con el modelo {expected}")
            logger.info(
                "Datos NPZ: X=%s Y=%s | celdas activas=%.4f",
                x_arr.shape,
                y_arr.shape,
                y_arr.mean(),
            )
            return make_datasets(x_arr, y_arr, args.batch_size, seed=seed)

        x_tr, y_tr, x_va, y_va = load_contract_cell_day(
            args.data,
            grid_size=grid,
            time_steps=time_steps,
            num_channels=num_channels,
            seed=seed,
            meteo_path=getattr(args, "meteo", None),
            rainfall_path=getattr(args, "rainfall", None),
            vegetation_path=getattr(args, "vegetation", None),
            validated_path=getattr(args, "validated", None),
            include_rejected=getattr(args, "include_rejected", False),
        )
        logger.info(
            "Datos VALEN (%s): train=%s val=%s | canales=%d | celdas activas=%.4f",
            os.path.basename(args.data.rstrip("/\\")),
            x_tr.shape,
            x_va.shape,
            num_channels,
            y_tr.mean() if len(y_tr) else 0.0,
        )
        return (
            _arrays_to_ds(x_tr, y_tr, args.batch_size, True, seed),
            _arrays_to_ds(x_va, y_va, args.batch_size, False, seed),
        )

    gen = SyntheticContractGenerator(grid, time_steps, num_channels, seed=seed)
    x_arr, y_arr = gen.generate(args.samples)
    logger.info(
        "Datos sintéticos (esquema VALEN->CATA): X=%s Y=%s | canales=%d %s | celdas en llamas=%.4f",
        x_arr.shape,
        y_arr.shape,
        num_channels,
        list(config.CHANNEL_REGISTRY[:num_channels]),
        y_arr.mean(),
    )
    return make_datasets(x_arr, y_arr, args.batch_size, seed=seed)


# ===========================================================================
# 5. Bucle de entrenamiento común
# ===========================================================================
def build_callbacks(
    out_path: str,
    tag: str,
    patience: int,
    has_validation: bool = True,
):
    os.makedirs(CHECKPOINTS_DIR, exist_ok=True)
    os.makedirs(config.LOG_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    monitor_metric = "val_loss" if has_validation else "loss"
    return [
        keras.callbacks.ModelCheckpoint(
            filepath=os.path.join(CHECKPOINTS_DIR, "best_model.keras"),
            monitor=monitor_metric,
            save_best_only=True,
            save_weights_only=False,
            verbose=1,
        ),
        keras.callbacks.ModelCheckpoint(
            filepath=os.path.join(CHECKPOINTS_DIR, "latest_backup.keras"),
            save_freq=500,
            save_best_only=False,
        ),
        keras.callbacks.EarlyStopping(
            monitor=monitor_metric,
            patience=5,
            restore_best_weights=True,
            verbose=1,
        ),
        keras.callbacks.CSVLogger(
            filename="training_log.csv",
            append=True,
        ),
    ]


def fit(model, train_ds, val_ds, epochs: int, out_path: str, tag: str, patience: int) -> dict:
    if epochs <= 0:
        return {}

    steps_per_epoch = STEPS_PER_EPOCH
    validation_steps = VALIDATION_STEPS if val_ds is not None else None
    if DRY_RUN:
        epochs = 2
        steps_per_epoch = 5
        validation_steps = 2 if val_ds is not None else None

    if hasattr(train_ds, "repeat"):
        train_ds = train_ds.repeat()
    if val_ds is not None and hasattr(val_ds, "repeat"):
        val_ds = val_ds.repeat()

    callbacks = build_callbacks(
        out_path,
        tag,
        patience,
        has_validation=(val_ds is not None),
    )

    try:
        history = model.fit(
            train_ds,
            validation_data=val_ds,
            epochs=epochs,
            steps_per_epoch=steps_per_epoch,
            validation_steps=validation_steps,
            callbacks=callbacks,
            verbose=2,
        )
    except KeyboardInterrupt:
        os.makedirs(CHECKPOINTS_DIR, exist_ok=True)
        interrupted_path = os.path.join(CHECKPOINTS_DIR, "interrupted_model.keras")
        print(f"\n[CATA] Entrenamiento interrumpido manualmente (Ctrl+C). Guardando estado en '{interrupted_path}'...")
        model.save(interrupted_path)
        print(f"[CATA] Modelo guardado limpiamente en '{interrupted_path}'. Saliendo sin errores.")
        return {}

    model.save(out_path)
    return {k: [float(v) for v in vals] for k, vals in history.history.items()}


def save_metadata(
    model_path: str,
    model: keras.Model,
    mode: str,
    history: dict,
    parent: str | None = None,
):
    """Sidecar JSON con el contrato de E/S VALEN -> CATA -> LUCIA."""
    cfg = extract_model_config(model)
    meta = {
        "algorithm": config.ALGORITHM_NAME,
        "source_validation_algorithm": config.SOURCE_VALIDATION_ALGORITHM,
        "target_routing_algorithm": config.TARGET_ROUTING_ALGORITHM,
        "schema_reference": "11_ML_DATA_CONTRACT.md + VALEN (CellDay, Meteo, Rainfall, Vegetation)",
        "grid_id": config.GRID_ID,
        "crs": config.CRS,
        "grid_level": config.GRID_LEVEL,
        "cell_size_m": config.CHUNK_SIZE_M,
        "quadrant_states": config.QUADRANT_LABELS,
        "quadrant_symbols": config.QUADRANT_SYMBOLS,
        "model_path": os.path.abspath(model_path),
        "mode": mode,
        "parent_checkpoint": parent,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "input_shape": [None, *cfg.input_shape],
        "output_shape": [None, cfg.height, cfg.width, 1],
        "channels": list(cfg.channel_names),
        "architecture": asdict(cfg),
        "final_metrics": {k: v[-1] for k, v in history.items()} if history else {},
    }
    with open(os.path.splitext(model_path)[0] + ".meta.json", "w") as f:
        json.dump(meta, f, indent=2)


def evaluate(model, val_ds, label: str) -> dict[str, float]:
    res = model.evaluate(val_ds, verbose=0, return_dict=True)
    logger.info("[%s] %s", label, "  ".join(f"{k}={v:.4f}" for k, v in res.items()))
    return res


def _maybe_export_predictions_for_lucia(
    model: keras.Model,
    args,
    default_export: bool = False,
) -> str | None:
    """Genera el archivo de predicciones de CATA para LUCIA si procede."""
    pred_out = getattr(args, "predictions_output", None)
    if not pred_out and not default_export:
        return None
    pred_out = pred_out or config.DEFAULT_PREDICTIONS_PATH

    cfg = extract_model_config(model)
    data_source = args.data
    if not data_source and os.path.exists(config.DEFAULT_VALEN_CELL_DAY_PATH):
        data_source = config.VALEN_OUTPUT_DIR

    if data_source and not data_source.endswith(".npz") and not data_source.endswith(".csv") and not data_source.endswith(".csv.gz"):
        try:
            x_tr, _, x_va, _, meta_tr, meta_va = load_contract_cell_day(
                data_source,
                grid_size=cfg.height,
                time_steps=cfg.time_steps,
                num_channels=cfg.num_channels,
                seed=args.seed,
                meteo_path=getattr(args, "meteo", None),
                rainfall_path=getattr(args, "rainfall", None),
                vegetation_path=getattr(args, "vegetation", None),
                validated_path=getattr(args, "validated", None),
                include_rejected=getattr(args, "include_rejected", False),
                return_patch_meta=True,
                target_date=getattr(args, "date", None),
            )
            # Tomamos las últimas ventanas temporales activas de cada bloque para predecir t+1
            all_x = np.concatenate([x_tr, x_va], axis=0) if len(x_tr) and len(x_va) else (x_tr if len(x_tr) else x_va)
            all_meta = (meta_tr + meta_va) if (meta_tr or meta_va) else []
            if len(all_x) > 0:
                max_zones = min(len(all_x), getattr(args, "max_prediction_zones", 8))
                # Seleccionar las ventanas con mayor actividad térmica reciente
                scores_act = all_x[:, -1, :, :, 0].sum(axis=(1, 2))
                top_idx = np.argsort(scores_act)[::-1][:max_zones]
                seq_batch = all_x[top_idx]
                origins_batch = [all_meta[int(i)] for i in top_idx] if all_meta else None
                export_cata_predictions_for_lucia(
                    model=model,
                    sequence=seq_batch,
                    output_path=pred_out,
                    patch_origins=origins_batch,
                )
                return pred_out
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fallback a muestra sintética para exportar predicciones (%s)", exc)

    sample_x, _ = SyntheticContractGenerator(
        cfg.height, cfg.time_steps, cfg.num_channels, seed=args.seed + 99
    ).generate(2)
    export_cata_predictions_for_lucia(
        model=model,
        sequence=sample_x,
        output_path=pred_out,
    )
    return pred_out


# ===========================================================================
# 6. Modos de ejecución (Algoritmo CATA)
# ===========================================================================
def run_scratch(args) -> str:
    cfg = ModelConfig(
        num_channels=args.channels,
        time_steps=args.time_steps,
        height=args.grid,
        width=args.grid,
    )
    out = args.output or os.path.join(config.MODEL_DIR, f"cata_c{cfg.num_channels}.keras")
    model = create_model(cfg, args.lr or config.LEARNING_RATE)
    model.summary(print_fn=logger.info)
    train_ds, val_ds = get_data(args, cfg.num_channels, cfg.height, cfg.time_steps)
    hist = fit(
        model, train_ds, val_ds, args.epochs, out, f"scratch_c{cfg.num_channels}", args.patience
    )
    save_metadata(out, model, "scratch", hist)
    logger.info("Modelo CATA guardado en %s", out)
    _maybe_export_predictions_for_lucia(model, args, default_export=True)
    return out


def run_finetune(args) -> str:
    _require_checkpoint(args)
    model = load_fire_model(args.checkpoint, learning_rate=args.lr or config.FINETUNE_LR)
    cfg = extract_model_config(model)
    out = args.output or args.checkpoint
    train_ds, val_ds = get_data(
        args, cfg.num_channels, cfg.height, cfg.time_steps, seed_offset=1000
    )
    evaluate(model, val_ds, "antes de fine-tuning")
    hist = fit(
        model, train_ds, val_ds, args.epochs, out, f"finetune_c{cfg.num_channels}", args.patience
    )
    evaluate(model, val_ds, "después de fine-tuning")
    save_metadata(out, model, "finetune", hist, parent=args.checkpoint)
    logger.info("Modelo CATA ajustado guardado en %s", out)
    _maybe_export_predictions_for_lucia(model, args, default_export=False)
    return out


def run_expand(args) -> str:
    _require_checkpoint(args)
    model = expand_model_channels(
        args.checkpoint,
        args.new_channels,
        new_channel_init=args.init,
        learning_rate=config.EXPAND_WARMUP_LR,
    )
    cfg = extract_model_config(model)
    out = args.output or os.path.join(config.MODEL_DIR, f"cata_c{cfg.num_channels}.keras")
    train_ds, val_ds = get_data(
        args, cfg.num_channels, cfg.height, cfg.time_steps, seed_offset=2000
    )
    evaluate(model, val_ds, "tras surgery (sin entrenar)")

    history: dict = {}
    if args.warmup_epochs > 0:
        set_expansion_warmup(model, True)
        compile_model(model, args.lr or config.EXPAND_WARMUP_LR)
        history["warmup"] = fit(
            model,
            train_ds,
            val_ds,
            args.warmup_epochs,
            out,
            f"expand_c{cfg.num_channels}_warmup",
            args.patience,
        )
    set_expansion_warmup(model, False)
    compile_model(model, config.EXPAND_LR)
    history["full"] = fit(
        model,
        train_ds,
        val_ds,
        args.epochs,
        out,
        f"expand_c{cfg.num_channels}_full",
        args.patience,
    )
    if not os.path.exists(out):
        model.save(out)
    evaluate(model, val_ds, "tras expansión + entrenamiento")
    save_metadata(
        out,
        model,
        "expand",
        history.get("full") or history.get("warmup") or {},
        parent=args.checkpoint,
    )
    logger.info("Modelo CATA expandido guardado en %s", out)
    _maybe_export_predictions_for_lucia(model, args, default_export=True)
    return out


def run_predict(args) -> str:
    """Carga un modelo CATA (o lo instancia) y exporta las predicciones de VALEN para LUCIA."""
    ckpt = args.checkpoint or config.DEFAULT_MODEL_PATH
    if os.path.exists(ckpt):
        model = load_fire_model(ckpt, compile_model_flag=False)
        logger.info("Modelo CATA cargado desde %s", ckpt)
    else:
        cfg = ModelConfig(
            num_channels=args.channels,
            time_steps=args.time_steps,
            height=args.grid,
            width=args.grid,
        )
        model = create_model(cfg)
        logger.info(
            "Checkpoint no encontrado (%s); usando modelo CATA inicializado con C=%d canales",
            ckpt,
            cfg.num_channels,
        )
    out_pred = _maybe_export_predictions_for_lucia(model, args, default_export=True)
    return out_pred or config.DEFAULT_PREDICTIONS_PATH


def run_demo(args) -> None:
    """Smoke test rápido de los modos encadenados (C=1 -> C=22 con VALEN) + predicción para LUCIA."""
    demo_dir = os.path.join(config.MODEL_DIR, "demo")
    base = os.path.join(demo_dir, "cata_c1.keras")

    saved_pred_out = args.predictions_output
    args.predictions_output = None

    args.channels, args.output = 1, base
    run_scratch(args)

    args.checkpoint, args.output = base, os.path.join(demo_dir, "cata_c1_finetuned.keras")
    run_finetune(args)

    args.checkpoint = args.output
    args.new_channels = args.new_channels or config.EXPANDED_NUM_CHANNELS
    args.output = os.path.join(demo_dir, f"cata_c{args.new_channels}.keras")
    args.predictions_output = saved_pred_out or config.DEFAULT_PREDICTIONS_PATH
    expanded_path = run_expand(args)

    # Demostración del marcado diferenciado de cuadrantes (1000x1000m):
    # Quemado real (F/B) vs Predicción pura en t+1 (P)
    model_exp = load_fire_model(expanded_path, compile_model_flag=False)
    sample_x, _ = SyntheticContractGenerator(
        args.grid, args.time_steps, args.new_channels, seed=args.seed + 99
    ).generate(1)
    q_res = cata_predict_quadrants(model_exp, sample_x[0])
    n_real = int(q_res["burned_real_mask"].sum())
    n_pred_only = int(q_res["predicted_only_mask"].sum())
    n_pers = int((q_res["state_matrix"] == config.QUADRANT_STATE_PERSISTENT).sum())
    logger.info(
        "Cuadrantes CATA (1000x1000m) -> Quemado REAL (F/B)=%d (persistente=%d) | "
        "Nuevos PREDICT (P)=%d",
        n_real,
        n_pers,
        n_pred_only,
    )
    logger.info(
        "DEMO CATA OK — modelos en %s | predicciones para LUCIA en %s",
        demo_dir,
        args.predictions_output,
    )


def _require_checkpoint(args):
    if not args.checkpoint:
        raise SystemExit(f"--checkpoint es obligatorio en modo '{args.mode}'")


# ===========================================================================
# 7. CLI
# ===========================================================================
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Entrenamiento y predicción del algoritmo CATA (integrado con VALEN -> salida para LUCIA)"
    )
    p.add_argument(
        "--mode",
        choices=["scratch", "finetune", "expand", "predict", "demo"],
        default="scratch",
    )
    p.add_argument("--channels", type=int, default=config.NUM_CHANNELS, help="C para modo scratch (defecto: 22 canales VALEN)")
    p.add_argument("--new-channels", type=int, default=None, help="C nuevo para modo expand (defecto: 22 canales VALEN)")
    p.add_argument(
        "--init",
        choices=["zeros", "glorot_uniform", "he_normal"],
        default="zeros",
        help="Inicialización de los pesos de los canales nuevos",
    )
    p.add_argument("--checkpoint", type=str, default=None, help="Modelo previo (.keras/.h5)")
    p.add_argument("--output", type=str, default=None, help="Ruta de salida del modelo (.keras)")
    p.add_argument(
        "--predictions-output",
        type=str,
        default=None,
        help="Ruta del archivo JSON de predicciones de CATA para LUCIA (defecto: artifacts/predictions/cata_predictions.json)",
    )
    p.add_argument(
        "--data",
        type=str,
        default=None,
        help="Carpeta output de VALEN, archivo cell_day/validated_cell_day (.parquet/.json) o dataset .npz",
    )
    p.add_argument("--meteo", type=str, default=None, help="Ruta opcional a cell_day_meteo.json de VALEN")
    p.add_argument("--rainfall", type=str, default=None, help="Ruta opcional a cell_day_rainfall.json de VALEN")
    p.add_argument("--vegetation", type=str, default=None, help="Ruta opcional a cell_day_vegetation.json de VALEN")
    p.add_argument("--validated", type=str, default=None, help="Ruta opcional a validated_cell_day.json/.parquet de VALEN")
    p.add_argument(
        "--include-rejected",
        action="store_true",
        help="Si se indica, incluye también las celdas descartadas como RECHAZA por VALEN",
    )
    p.add_argument("--max-prediction-zones", type=int, default=8, help="Nº máximo de zonas activas a exportar para LUCIA")
    p.add_argument("--date", type=str, default=None, help="Fecha objetivo (YYYY-MM-DD) para --mode predict (toma los 5 días previos)")
    p.add_argument("--samples", type=int, default=config.SYNTH_NUM_SAMPLES)
    p.add_argument("--grid", type=int, default=config.GRID_SIZE)
    p.add_argument("--time-steps", type=int, default=config.TIME_STEPS)
    p.add_argument("--epochs", type=int, default=config.EPOCHS)
    p.add_argument("--warmup-epochs", type=int, default=2)
    p.add_argument("--batch-size", type=int, default=config.BATCH_SIZE)
    p.add_argument("--lr", type=float, default=None, help="Sobrescribe el LR del modo")
    p.add_argument("--patience", type=int, default=config.EARLY_STOPPING_PATIENCE)
    p.add_argument("--seed", type=int, default=config.SEED)
    args = p.parse_args(argv)

    if args.mode == "demo":
        if args.samples == config.SYNTH_NUM_SAMPLES:
            args.samples = 96
        if args.epochs == config.EPOCHS:
            args.epochs = 2
        args.warmup_epochs = min(args.warmup_epochs, 1)
    if args.mode == "expand" and not args.new_channels:
        args.new_channels = config.EXPANDED_NUM_CHANNELS
    return args


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = parse_args(argv)
    keras.utils.set_random_seed(args.seed)
    {
        "scratch": run_scratch,
        "finetune": run_finetune,
        "expand": run_expand,
        "predict": run_predict,
        "demo": run_demo,
    }[args.mode](args)


if __name__ == "__main__":
    main()
