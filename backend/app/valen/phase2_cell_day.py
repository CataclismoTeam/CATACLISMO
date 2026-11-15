#!/usr/bin/env python3
"""
Algoritmo VALEN (Fase 2) — Agregación cell_day (grano: cell_id + date + sensor)

Lee observations.parquet (Fase 1), agrupa por (cell_id_L0, date, sensor)
y genera cell_day.parquet + cell_day.json (array único) con 15 campos contractuales.

Uso:
    python phase2_cell_day.py \
        --input backend/app/valen/output/observations.parquet \
        --output backend/app/valen/output \
        --cell-size 1000
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from pyproj import Transformer
    _TRANSFORMER_INV = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
except ImportError:
    _TRANSFORMER_INV = None
    try:
        from .laea import epsg3035_to_lonlat as _laea_inv
    except ImportError:
        from laea import epsg3035_to_lonlat as _laea_inv

ALGORITHM_NAME: str = "valen"

# ---------------------------------------------------------------------------
# Configuración de logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("valen.phase2_cell_day")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

class _FallbackTransformerInv:
    @staticmethod
    def transform(x_val, y_val):
        return _laea_inv(float(x_val), float(y_val))

TRANSFORMER_INV = _TRANSFORMER_INV if _TRANSFORMER_INV is not None else _FallbackTransformerInv()

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def parse_cell_id(cell_id: str) -> tuple[int, int, int] | None:
    """Parsea 'ES1K:L0:Y{iy}:X{ix}' -> (level, iy, ix)."""
    try:
        parts = str(cell_id).strip().split(":")
        if len(parts) != 4 or not parts[0].startswith("ES"):
            return None
        level = int(parts[1][1:])
        iy = int(parts[2][1:])
        ix = int(parts[3][1:])
        return level, iy, ix
    except Exception:
        return None


def cell_centroid_lonlat(iy: int, ix: int, cell_size: float) -> list[float]:
    """Centro geométrico de la celda en lon/lat (WGS84)."""
    x_center = (ix + 0.5) * cell_size
    y_center = (iy + 0.5) * cell_size
    lon, lat = TRANSFORMER_INV.transform(x_center, y_center)
    return [float(lon), float(lat)]


def format_cell_id(iy: int, ix: int, level: int, grid_prefix: str) -> str:
    """Formatea cell_id: {grid_prefix}:L{level}:Y{iy}:X{ix}."""
    return f"{grid_prefix}:L{level}:Y{iy:05d}:X{ix:05d}"


def compute_parent_ids(iy: int, ix: int, grid_prefix: str) -> dict[str, str]:
    """Calcula parent_ids para L1, L2, L3 (anidamiento 2×2)."""
    parents = {}
    for level in (1, 2, 3):
        p_iy = iy // (2 ** level)
        p_ix = ix // (2 ** level)
        parents[f"L{level}"] = f"{grid_prefix}:L{level}:Y{p_iy:05d}:X{p_ix:05d}"
    return parents


def infer_grid_prefix(cell_size: int) -> str:
    """Deriva grid_prefix del cell_size (estándar 1000 m -> ES1K)."""
    size_km = cell_size // 1000
    return f"ES{size_km}K"


def load_observations(parquet_path: Path) -> pd.DataFrame:
    """Carga observations.parquet."""
    df = pd.read_parquet(parquet_path)
    logger.info(f"Cargadas {len(df)} observaciones de {parquet_path}")
    return df


def aggregate_cell_day(
    df: pd.DataFrame,
    cell_size: float,
    grid_prefix: str
) -> pd.DataFrame:
    """Agrupa por (cell_id_L0, date, sensor) y calcula 15 campos contractuales."""
    required = ["cell_id_L0", "acq_date", "sensor", "frp", "daynight", "platform",
                "confidence_rank", "scan", "track", "product", "flags"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas en observations: {missing}")

    df = df.copy()
    df["group_key"] = df["cell_id_L0"].astype(str) + "|" + df["acq_date"].astype(str) + "|" + df["sensor"].astype(str)

    grouped = df.groupby("group_key", observed=True)

    results = []

    for key, group in grouped:
        cell_id, date_str, sensor = key.split("|", 2)

        parsed = parse_cell_id(cell_id)
        if parsed is None:
            logger.warning(f"cell_id inválido {cell_id}, se omite")
            continue
        level, iy, ix = parsed

        n_obs = len(group)
        n_day = int((group["daynight"] == "D").sum())
        n_night = int((group["daynight"] == "N").sum())
        n_platforms = group["platform"].nunique()
        n_high_conf = int((group["confidence_rank"] == 2).sum())
        confidence_rank_max = int(group["confidence_rank"].max())

        frp_vals = pd.to_numeric(group["frp"], errors="coerce").dropna()
        frp_sum_mw = float(frp_vals.sum()) if len(frp_vals) > 0 else 0.0
        frp_mean_mw = float(frp_vals.mean()) if len(frp_vals) > 0 else 0.0
        frp_max_mw = float(frp_vals.max()) if len(frp_vals) > 0 else 0.0
        frp_p50_mw = float(frp_vals.median()) if len(frp_vals) > 0 else 0.0

        scan_vals = pd.to_numeric(group["scan"], errors="coerce")
        track_vals = pd.to_numeric(group["track"], errors="coerce")
        footprint_max_km = 0.0
        if scan_vals.notna().any() and track_vals.notna().any():
            max_dims = np.maximum(scan_vals, track_vals)
            footprint_max_km = float(max_dims.max())

        n_nrt = int((group["product"] == "NRT").sum())
        product_mix = n_nrt / n_obs if n_obs > 0 else 0.0

        all_flags = set()
        for fl in group["flags"]:
            if isinstance(fl, (list, np.ndarray)):
                all_flags.update(fl)
        if 0.05 < product_mix < 0.95:
            all_flags.add("sp_nrt_hybrid")
        flags = sorted(all_flags)

        parsed = parse_cell_id(group["cell_id_L0"].iloc[0])
        if parsed:
            _, iy, ix = parsed
            centroid = cell_centroid_lonlat(iy, ix, float(cell_size))
            parent_ids = compute_parent_ids(iy, ix, grid_prefix)
        else:
            centroid = [0.0, 0.0]
            parent_ids = {}

        dt = pd.to_datetime(date_str).date()
        iso_year = dt.isocalendar()[0]
        iso_week = dt.isocalendar()[1]
        year_month = dt.strftime("%Y-%m")

        row = {
            "row_id": f"{cell_id}|{date_str}|{sensor}",
            "cell_id": cell_id,
            "level": 0,
            "parent_ids": parent_ids,
            "cell_centroid_lonlat": centroid,
            "cell_area_km2": round((float(cell_size) / 1000.0) ** 2, 6),
            "date": date_str,
            "iso_year": iso_year,
            "iso_week": iso_week,
            "year_month": year_month,
            "sensor": sensor,
            "n_obs": n_obs,
            "n_day": n_day,
            "n_night": n_night,
            "n_platforms": n_platforms,
            "n_high_conf": n_high_conf,
            "confidence_rank_max": confidence_rank_max,
            "frp_sum_mw": frp_sum_mw,
            "frp_mean_mw": frp_mean_mw,
            "frp_max_mw": frp_max_mw,
            "frp_p50_mw": frp_p50_mw,
            "footprint_max_km": footprint_max_km,
            "product_mix": round(product_mix, 4),
            "sensor_day_observed": None,
            "coverage_fraction": None,
            "flags": flags,
        }
        results.append(row)

    cell_day_df = pd.DataFrame(results)
    logger.info(f"Agregados {len(cell_day_df)} cell-days ({cell_day_df['sensor'].value_counts().to_dict()})")
    return cell_day_df


def validate_cell_day(cell_day: pd.DataFrame, observations: pd.DataFrame) -> None:
    """Validaciones contractuales obligatorias."""
    logger.info("\n=== VALIDACIONES CELL_DAY ===")
    logger.info(f"Filas totales: {len(cell_day)}")
    logger.info(f"Por sensor:\n{cell_day['sensor'].value_counts().to_string()}")

    for sensor in ["MODIS", "VIIRS"]:
        obs_count = len(observations[observations["sensor"] == sensor])
        cd_sum = int(cell_day[cell_day["sensor"] == sensor]["n_obs"].sum())
        ok = obs_count == cd_sum
        logger.info(f"  {sensor}: observations={obs_count}, cell_day.n_obs.sum()={cd_sum} {'OK' if ok else 'MISMATCH'}")

    dup = cell_day["row_id"].duplicated().sum()
    logger.info(f"row_id duplicados: {dup}")
    if dup > 0:
        raise ValueError(f"Hay {dup} row_id duplicados")

    logger.info(f"cell_area_km2 único: {cell_day['cell_area_km2'].unique()}")

    dates = pd.to_datetime(cell_day["date"], errors="coerce")
    logger.info(f"Rango fechas: {dates.min()} -> {dates.max()}")

    all_flags = []
    for fl in cell_day["flags"]:
        if isinstance(fl, list):
            all_flags.extend(fl)
    if all_flags:
        from collections import Counter
        flag_counts = Counter(all_flags)
        logger.info("Flags:")
        for flag, count in flag_counts.most_common():
            logger.info(f"  {flag}: {count}")

    null_sdo = cell_day["sensor_day_observed"].isna().sum()
    null_cf = cell_day["coverage_fraction"].isna().sum()
    logger.info(f"sensor_day_observed null: {null_sdo}/{len(cell_day)}")
    logger.info(f"coverage_fraction null: {null_cf}/{len(cell_day)}")

    logger.info("=== FIN VALIDACIONES ===\n")


def write_outputs(cell_day: pd.DataFrame, output_dir: Path) -> None:
    """Escribe Parquet y JSON (array único)."""
    try:
        from .json_output import JSONArrayWriter
    except ImportError:
        from json_output import JSONArrayWriter

    parquet_path = output_dir / "cell_day.parquet"
    json_path = output_dir / "cell_day.json"

    cell_day.to_parquet(parquet_path, compression="zstd", index=False)
    logger.info(f"Escrito Parquet: {parquet_path} ({parquet_path.stat().st_size / 1024:.1f} KB)")

    with JSONArrayWriter(json_path, indent=2) as w:
        for _, row in cell_day.iterrows():
            rec = row.to_dict()
            for k, v in rec.items():
                if isinstance(v, (np.integer, np.floating)):
                    rec[k] = v.item() if not np.isnan(v) else None
                elif isinstance(v, np.ndarray):
                    rec[k] = v.tolist()
                elif isinstance(v, (pd.Timestamp, date)):
                    rec[k] = v.isoformat() if not pd.isna(v) else None
                elif hasattr(v, 'isoformat'):
                    rec[k] = v.isoformat()
            w.write(rec)
    logger.info(f"Escrito JSON: {json_path} ({json_path.stat().st_size / 1024:.1f} KB)")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Algoritmo VALEN — Fase 2: Agregación cell_day")
    p.add_argument("--input", type=Path, required=True,
                   help="observations.parquet de Fase 1")
    p.add_argument("--output", type=Path, required=True,
                   help="Directorio de salida")
    p.add_argument("--cell-size", type=int, default=1000,
                   help="Tamaño de celda L0 en metros (default: 1000)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    grid_prefix = infer_grid_prefix(args.cell_size)
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        logger.info("=== FASE 2: Agregación cell_day ===")
        logger.info(f"Cell size: {args.cell_size} m")
        logger.info(f"Entrada: {args.input}")
        logger.info(f"Salida: {output_dir}")

        observations = load_observations(args.input)
        cell_day = aggregate_cell_day(observations, args.cell_size, infer_grid_prefix(args.cell_size))
        validate_cell_day(cell_day, observations)
        write_outputs(cell_day, output_dir)

        logger.info("OK - FASE 2 completada correctamente")
        return 0

    except Exception as e:
        logger.error(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())