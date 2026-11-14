#!/usr/bin/env python3
"""
Algoritmo de Scoring Multi-fuente para Fase 3b — Validación Inteligente.

Combina:
- Sensores (MODIS/VIIRS) y confidence
- Meteorología (Meteomatics: FWI, viento, humedad, índices)
- Vegetación (WorldCover + IFN3: inflamabilidad)
- Lluvia (NASA POWER: días sin lluvia, precipitación, rachas secas)

Salida: `validated_cell_day.parquet` con decisión ACEPTA/RECHAZA/REVISAR_MANUAL.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuración de pesos (ajustables)
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    # Sensores y calidad detección
    "sensor_count": 0.20,        # MODIS+VIIRS=3, solo VIIRS=2, solo MODIS=1
    "confidence_rank_max": 0.15, # 0/1/2 normalizado
    "n_high_conf_ratio": 0.05,   # n_high_conf / n_obs

    # Meteorología (Meteomatics)
    "fwi": 0.15,                 # Fire Weather Index (0-100+)
    "wind_speed": 0.10,          # Viento >30 km/h
    "humidity": 0.10,            # Humedad relativa <30%

    # Sequía / Lluvia (NASA POWER)
    "days_since_rain_1mm": 0.10, # Días sin lluvia ≥1mm
    "dry_spell_max": 0.05,       # Máxima racha seca
    "precip_30d": 0.05,          # Precipitación 30 días (inverso)

    # Vegetación
    "vegetation_flammability": 0.10,  # combined_flammability 1-5

    # Geometría / Calidad dato
    "boundary_crossing": 0.05,   # Flag boundary_crossing
    "product_mix_nrt": 0.05,     # product_mix (NRT=1, SP=0)
}

# Umbrales de decisión
DEFAULT_THRESHOLDS = {
    "accept": 0.70,       # ≥ 0.70 → ACEPTA
    "review": 0.30,       # 0.30-0.70 → REVISAR_MANUAL
    # < 0.30 → RECHAZA
}

# Normalización de variables (min-max o sigmoid)
NORMALIZATION = {
    "fwi": {"type": "minmax", "min": 0, "max": 50},           # FWI típico 0-50
    "wind_speed": {"type": "minmax", "min": 0, "max": 20},    # m/s
    "humidity": {"type": "inverse_minmax", "min": 10, "max": 90},  # % (inverso: menos humedad = más riesgo)
    "days_since_rain_1mm": {"type": "minmax", "min": 0, "max": 30},
    "dry_spell_max": {"type": "minmax", "min": 0, "max": 30},
    "precip_30d": {"type": "inverse_minmax", "min": 0, "max": 100},  # mm (inverso)
    "vegetation_flammability": {"type": "minmax", "min": 1, "max": 5},
    "confidence_rank_max": {"type": "minmax", "min": 0, "max": 2},
    "sensor_count": {"type": "minmax", "min": 1, "max": 3},
    "n_high_conf_ratio": {"type": "minmax", "min": 0, "max": 1},
    "boundary_crossing": {"type": "binary"},  # 0/1
    "product_mix_nrt": {"type": "direct"},    # 0-1
}


# ---------------------------------------------------------------------------
# Utilidades de normalización
# ---------------------------------------------------------------------------

def normalize_value(value: float | None, spec: dict) -> float:
    """Normaliza un valor según especificación (0-1)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return 0.0  # Valor faltante = riesgo mínimo (conservador)

    ntype = spec.get("type", "minmax")
    vmin = spec.get("min", 0)
    vmax = spec.get("max", 1)

    if ntype == "minmax":
        return float(np.clip((value - vmin) / (vmax - vmin), 0, 1))
    elif ntype == "inverse_minmax":
        return float(np.clip(1 - (value - vmin) / (vmax - vmin), 0, 1))
    elif ntype == "binary":
        return 1.0 if value else 0.0
    elif ntype == "direct":
        return float(np.clip(value, 0, 1))
    else:
        return 0.0


def extract_features(row: pd.Series) -> dict[str, float]:
    """Extrae y normaliza features de una fila combinada (cell_day + enriquecidos)."""
    features = {}

    # 1. Sensor count (1=MODIS, 2=VIIRS, 3=ambos)
    # En cell_day original vienen separados; aquí asumimos columna 'sensors_present'
    # que sería 'MODIS', 'VIIRS' o 'BOTH'
    sensors = row.get("sensors_present", "UNKNOWN")
    if sensors == "BOTH":
        sensor_count = 3
    elif sensors == "VIIRS":
        sensor_count = 2
    elif sensors == "MODIS":
        sensor_count = 1
    else:
        # Inferir de n_obs por sensor si existe
        sensor_count = 1
    features["sensor_count"] = normalize_value(sensor_count, NORMALIZATION["sensor_count"])

    # 2. Confidence rank max (0-2)
    features["confidence_rank_max"] = normalize_value(
        row.get("confidence_rank_max"), NORMALIZATION["confidence_rank_max"]
    )

    # 3. n_high_conf ratio
    n_obs = row.get("n_obs", 1)
    n_high = row.get("n_high_conf", 0)
    features["n_high_conf_ratio"] = normalize_value(
        n_high / max(n_obs, 1), NORMALIZATION["n_high_conf_ratio"]
    )

    # 4. FWI (Meteomatics)
    fwi = row.get("fwi") or row.get("fire_weather_index")
    features["fwi"] = normalize_value(fwi, NORMALIZATION["fwi"])

    # 5. Wind speed (m/s)
    wind = row.get("wind_speed_10m") or row.get("wind_speed")
    features["wind_speed"] = normalize_value(wind, NORMALIZATION["wind_speed"])

    # 6. Humidity (%)
    hum = row.get("relative_humidity_2m") or row.get("humidity")
    features["humidity"] = normalize_value(hum, NORMALIZATION["humidity"])

    # 7. Days since rain 1mm
    dsr = row.get("days_since_rain_1mm")
    features["days_since_rain_1mm"] = normalize_value(dsr, NORMALIZATION["days_since_rain_1mm"])

    # 8. Dry spell max
    dsm = row.get("dry_spell_max_days")
    features["dry_spell_max"] = normalize_value(dsm, NORMALIZATION["dry_spell_max"])

    # 9. Precip 30d (inverso)
    p30 = row.get("precip_30d_mm")
    features["precip_30d"] = normalize_value(p30, NORMALIZATION["precip_30d"])

    # 10. Vegetation flammability (1-5)
    vf = row.get("combined_flammability") or row.get("vegetation_flammability")
    features["vegetation_flammability"] = normalize_value(vf, NORMALIZATION["vegetation_flammability"])

    # 11. Boundary crossing (binary)
    flags = row.get("flags", [])
    if isinstance(flags, str):
        import ast
        try:
            flags = ast.literal_eval(flags)
        except:
            flags = []
    bc = 1 if "boundary_crossing" in flags else 0
    features["boundary_crossing"] = normalize_value(bc, NORMALIZATION["boundary_crossing"])

    # 12. Product mix NRT (0-1)
    pmix = row.get("product_mix", 0)
    features["product_mix_nrt"] = normalize_value(pmix, NORMALIZATION["product_mix_nrt"])

    return features


def compute_score(features: dict[str, float], weights: dict[str, float] = None) -> float:
    """Calcula score ponderado (0-1)."""
    if weights is None:
        weights = DEFAULT_WEIGHTS

    score = 0.0
    total_weight = 0.0
    for feat, weight in weights.items():
        if feat in features:
            score += features[feat] * weight
            total_weight += weight

    return score / total_weight if total_weight > 0 else 0.0


def decide(score: float, thresholds: dict = None) -> str:
    """Decisión basada en score."""
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if score >= thresholds["accept"]:
        return "ACEPTA"
    elif score >= thresholds["review"]:
        return "REVISAR_MANUAL"
    else:
        return "RECHAZA"


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def load_enrichment_file(path: Path) -> pd.DataFrame:
    """Carga JSONL de enriquecimiento (meteo, veg, lluvia)."""
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))
    return pd.DataFrame(records)


def merge_enrichments(
    cell_day: pd.DataFrame,
    meteo_path: Path | None,
    veg_path: Path | None,
    rain_path: Path | None,
) -> pd.DataFrame:
    """Une cell_day con archivos de enriquecimiento."""
    df = cell_day.copy()

    # Meteo
    if meteo_path and meteo_path.exists():
        meteo = load_enrichment_file(meteo_path)
        # meteo tiene cell_id, date, parameters...
        # Para simplificar, asumimos que ya vienen aplanados
        pass

    # Vegetación
    if veg_path and veg_path.exists():
        veg = load_enrichment_file(veg_path)
        # veg: cell_id, worldcover, ifn3, combined_flammability
        veg_lookup = {}
        for _, r in veg.iterrows():
            cid = r.get("cell_id")
            if cid:
                veg_lookup[cid] = {
                    "combined_flammability": r.get("combined_flammability"),
                    "worldcover_class": r.get("worldcover", {}).get("class_name"),
                    "ifn3_dominant": r.get("ifn3", {}).get("dominant_species"),
                }
        df["combined_flammability"] = df["cell_id"].map(
            lambda x: veg_lookup.get(x, {}).get("combined_flammability")
        )

    # Lluvia
    if rain_path and rain_path.exists():
        rain = load_enrichment_file(rain_path)
        rain_lookup = {}
        for _, r in rain.iterrows():
            key = (r.get("cell_id"), r.get("reference_date") or r.get("date"))
            rain_lookup[key] = r
        # Merge por cell_id + date
        def get_rain(row):
            key = (row["cell_id"], str(row["date"]))
            return rain_lookup.get(key, {})
        rain_data = df.apply(get_rain, axis=1)
        for col in ["days_since_rain_1mm", "days_since_rain_10mm",
                    "precip_7d_mm", "precip_30d_mm", "precip_90d_mm",
                    "dry_spell_max_days", "rain_days_30d"]:
            df[col] = rain_data.apply(lambda x: x.get(col))

    return df


def run_scoring(
    cell_day_path: Path,
    output_path: Path,
    meteo_path: Path | None = None,
    veg_path: Path | None = None,
    rain_path: Path | None = None,
    weights: dict = None,
    thresholds: dict = None,
) -> pd.DataFrame:
    """Ejecuta scoring completo sobre cell_day."""
    cell_day = pd.read_parquet(cell_day_path)
    print(f"Cargados {len(cell_day)} cell-days")

    # Merge enriquecimientos
    df = merge_enrichments(cell_day, meteo_path, veg_path, rain_path)

    # Para sensors_present, necesitamos saber qué sensores hay en cada cell_id+date
    # cell_day ya está separado por sensor; creamos columna combinada
    sensor_map = df.groupby(["cell_id", "date"])["sensor"].apply(
        lambda x: "BOTH" if set(x) == {"MODIS", "VIIRS"} else list(x)[0]
    ).reset_index(name="sensors_present")
    df = df.merge(sensor_map, on=["cell_id", "date"], how="left")

    # Calcular score por fila
    results = []
    for _, row in df.iterrows():
        features = extract_features(row)
        score = compute_score(features, weights)
        decision = decide(score, thresholds)

        result = {
            "cell_id": row["cell_id"],
            "date": str(row["date"]),
            "sensor": row["sensor"],
            "score": round(score, 4),
            "decision": decision,
            "features": features,
            "scored_at": datetime.now(timezone.utc).isoformat(),
        }
        results.append(result)

    results_df = pd.DataFrame(results)

    # Estadísticas
    print(f"\n=== RESULTADOS SCORING ===")
    print(f"Total: {len(results_df)}")
    print(f"Decisiones: {results_df['decision'].value_counts().to_dict()}")
    print(f"Score mean: {results_df['score'].mean():.4f}")
    print(f"Score std: {results_df['score'].std():.4f}")

    # Guardar
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_parquet(output_path, compression="zstd", index=False)
    print(f"Guardado: {output_path}")

    return results_df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser():
    import argparse
    p = argparse.ArgumentParser(description="Scoring Multi-fuente Fase 3b")
    p.add_argument("--cell-day", type=Path, required=True, help="cell_day.parquet")
    p.add_argument("--output", type=Path, required=True, help="validated_cell_day.parquet")
    p.add_argument("--meteo", type=Path, help="cell_day_meteo.jsonl")
    p.add_argument("--veg", type=Path, help="cell_day_vegetation.jsonl")
    p.add_argument("--rain", type=Path, help="cell_day_rainfall.jsonl")
    p.add_argument("--weights", type=str, help="JSON string con pesos personalizados")
    p.add_argument("--accept-threshold", type=float, default=0.70)
    p.add_argument("--review-threshold", type=float, default=0.30)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    weights = DEFAULT_WEIGHTS.copy()
    if args.weights:
        weights.update(json.loads(args.weights))

    thresholds = {
        "accept": args.accept_threshold,
        "review": args.review_threshold,
    }

    run_scoring(
        args.cell_day,
        args.output,
        meteo_path=args.meteo,
        veg_path=args.veg,
        rain_path=args.rain,
        weights=weights,
        thresholds=thresholds,
    )
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())