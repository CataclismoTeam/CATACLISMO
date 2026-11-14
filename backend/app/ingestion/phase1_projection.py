#!/usr/bin/env python3
"""
Fase 1 — Proyección EPSG:3035 + Asignación a celdas L0–L3 (GENÉRICO)

Lee archivos JSON de FIRMS (MODIS/VIIRS, SP/NRT), aplica tipos, proyecta a EPSG:3035,
calcula celdas anidadas 2×2, añade control de calidad y trazabilidad,
y escribe observations.parquet + observations.jsonl.

Uso:
    python phase1_projection.py \
        --input /ruta/a/json1.json /ruta/a/directorio/ \
        --output ./output \
        --cell-size 1000 \
        --grid-prefix ES1K

Entrada: archivos JSON (array de objetos) o directorios (recursivo)
Salida: observations.parquet + observations.jsonl en --output
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Transformer

# ---------------------------------------------------------------------------
# Constantes y umbrales (configurables vía CLI)
# ---------------------------------------------------------------------------

# Proyección EPSG:4326 (WGS84) -> EPSG:3035 (ETRS89-LAEA Europe, metros)
TRANSFORMER = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)

# Umbrales de saturación por sensor
SATURATION_THRESHOLDS = {
    "VIIRS": {"brightness_max": 367.0, "brightness_min": 208.0},
    "MODIS": {"brightness_max": 500.0},
}

# Canarias: x_3035 < 2_500_000 metros (en EPSG:3035)
CANARIAS_X_THRESHOLD = 2_500_000

# Periodo incompleto (por defecto, configurable)
DEFAULT_PARTIAL_PERIOD_START = "2026-09-01"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def compute_file_hash(path: Path) -> str:
    """SHA-256 del archivo original."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_acq_time(acq_time: str | int | float) -> int | None:
    """Convierte 'HHMM' o 1340 -> minutos del día (0-1439)."""
    if acq_time is None or (isinstance(acq_time, float) and np.isnan(acq_time)):
        return None
    s = str(int(acq_time)).zfill(4)
    try:
        hh = int(s[:2])
        mm = int(s[2:])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh * 60 + mm
    except ValueError:
        pass
    return None


def confidence_to_rank(sensor: str, confidence_raw: Any) -> int | None:
    """
    Convierte confidence crudo a rank 0/1/2.
    MODIS: string numérica "0"-"100" -> <30=0, 30-79=1, >=80=2
    VIIRS: "l"/"n"/"h" -> l=0, n=1, h=2
    """
    if confidence_raw is None or (isinstance(confidence_raw, float) and np.isnan(confidence_raw)):
        return None

    sensor_upper = sensor.upper()
    val = str(confidence_raw).strip().lower()

    if sensor_upper == "MODIS":
        try:
            v = int(val)
            if v < 30:
                return 0
            elif v < 80:
                return 1
            else:
                return 2
        except ValueError:
            return None

    elif sensor_upper == "VIIRS":
        if val in ("l", "low"):
            return 0
        elif val in ("n", "nominal"):
            return 1
        elif val in ("h", "high"):
            return 2
        return None

    return None


def infer_product_from_filename(fname: str) -> str:
    """Deriva SP/NRT del nombre del archivo."""
    fname_lower = fname.lower()
    if "archive" in fname_lower:
        return "SP"
    elif "nrt" in fname_lower:
        return "NRT"
    return "unknown"


def compute_flags(row: pd.Series, cell_size: float, partial_period_start: str) -> list[str]:
    """Genera lista de flags según catálogo cerrado."""
    flags = []
    sensor = row.get("sensor", "").upper()

    # frp_zero
    frp = row.get("frp")
    if frp is not None:
        try:
            if float(frp) == 0.0:
                flags.append("frp_zero")
        except (ValueError, TypeError):
            pass

    # brightness_saturated
    brightness = row.get("brightness")
    if brightness is not None:
        try:
            b = float(brightness)
            if sensor == "VIIRS" and (b == 367.0 or b == 208.0):
                flags.append("brightness_saturated")
            elif sensor == "MODIS" and b >= 500.0:
                flags.append("brightness_saturated")
        except (ValueError, TypeError):
            pass

    # nrt
    if row.get("product") == "NRT":
        flags.append("nrt")

    # boundary_crossing: footprint toca otra celda
    scan = row.get("scan")
    track = row.get("track")
    x_3035 = row.get("x_3035")
    y_3035 = row.get("y_3035")
    if all(v is not None for v in (scan, track, x_3035, y_3035)):
        try:
            scan_km = float(scan)
            track_km = float(track)
            max_dim_m = max(scan_km, track_km) * 1000.0  # metros
            half = max_dim_m / 2.0
            ix = np.floor(x_3035 / cell_size)
            iy = np.floor(y_3035 / cell_size)
            x_min_cell = ix * cell_size
            x_max_cell = (ix + 1) * cell_size
            y_min_cell = iy * cell_size
            y_max_cell = (iy + 1) * cell_size
            footprint_x_min = x_3035 - half
            footprint_x_max = x_3035 + half
            footprint_y_min = y_3035 - half
            footprint_y_max = y_3035 + half
            if (footprint_x_min < x_min_cell or footprint_x_max > x_max_cell or
                footprint_y_min < y_min_cell or footprint_y_max > y_max_cell):
                flags.append("boundary_crossing")
        except (ValueError, TypeError):
            pass

    # island_domain (Canarias)
    if x_3035 is not None:
        try:
            if float(x_3035) < CANARIAS_X_THRESHOLD:
                flags.append("island_domain")
        except (ValueError, TypeError):
            pass

    # partial_period
    acq_date = row.get("acq_date")
    if acq_date is not None:
        try:
            if str(acq_date) >= partial_period_start:
                flags.append("partial_period")
        except (ValueError, TypeError):
            pass

    return flags


def format_cell_id(iy: int, ix: int, level: int, grid_prefix: str) -> str:
    """Formatea cell_id: {grid_prefix}:L{level}:Y{iy}:X{ix} con zero-padding 5 dígitos con signo."""
    return f"{grid_prefix}:L{level}:Y{iy:05d}:X{ix:05d}"


def compute_parent_ids(iy: int, ix: int, grid_prefix: str) -> dict[str, str]:
    """Calcula parent_ids para L1, L2, L3 (anidamiento 2×2)."""
    parents = {}
    for level in (1, 2, 3):
        p_iy = iy // (2 ** level)
        p_ix = ix // (2 ** level)
        parents[f"L{level}"] = format_cell_id(p_iy, p_ix, level, grid_prefix)
    return parents


def collect_input_files(input_paths: list[Path]) -> list[Path]:
    """Expande rutas de entrada (archivos o directorios) a lista de archivos JSON."""
    files = []
    for path in input_paths:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".json":
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.json")))
        else:
            print(f"ADVERTENCIA: {path} no existe o no es .json/.directorio, se omite", file=sys.stderr)
    return files


def load_json_files(file_paths: list[Path]) -> pd.DataFrame:
    """Carga múltiples JSON y devuelve DataFrame combinado con columnas src_*."""
    all_records = []
    file_hashes = {}

    for fpath in file_paths:
        file_hashes[fpath.name] = compute_file_hash(fpath)

        with fpath.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            print(f"ADVERTENCIA: {fpath.name} no es una lista, se omite", file=sys.stderr)
            continue

        for idx, record in enumerate(data):
            if not isinstance(record, dict):
                continue
            rec = {
                "source_file": fpath.name,
                "source_row": idx,
            }
            for k, v in record.items():
                rec[f"src_{k}"] = v
            all_records.append(rec)

    if not all_records:
        raise RuntimeError("No se cargaron registros de ningún archivo JSON")

    df = pd.DataFrame(all_records)
    print(f"Cargados {len(df)} registros de {len(file_hashes)} archivos")
    for fname, h in file_hashes.items():
        print(f"  {fname}: sha256={h[:16]}...")
    return df


def normalize_and_enrich(df: pd.DataFrame, cell_size: float, grid_prefix: str, partial_period_start: str) -> pd.DataFrame:
    """Aplica tipos, proyección, celdas, ranks, flags, IDs."""
    # --- Tipos básicos ---
    df["latitude"] = pd.to_numeric(df.get("src_latitude"), errors="coerce")
    df["longitude"] = pd.to_numeric(df.get("src_longitude"), errors="coerce")

    df["acq_date"] = pd.to_datetime(df.get("src_acq_date"), errors="coerce").dt.date
    df["acq_minute"] = df.get("src_acq_time").apply(parse_acq_time)

    df["sensor"] = df.get("src_instrument").replace({"SNPP": "VIIRS"}).fillna(
        df.get("src_sensor")
    ).str.upper()
    df["platform"] = df.get("src_satellite").fillna(df.get("src_platform")).str.title()
    df["product"] = df["source_file"].apply(infer_product_from_filename)

    df["frp"] = pd.to_numeric(df.get("src_frp"), errors="coerce")
    df["brightness"] = pd.to_numeric(df.get("src_brightness"), errors="coerce")
    df["bright_t31"] = pd.to_numeric(df.get("src_bright_t31"), errors="coerce")
    df["scan"] = pd.to_numeric(df.get("src_scan"), errors="coerce")
    df["track"] = pd.to_numeric(df.get("src_track"), errors="coerce")

    df["confidence_raw"] = df.get("src_confidence").astype(str)
    df["confidence_rank"] = df.apply(
        lambda r: confidence_to_rank(r.get("sensor", ""), r.get("confidence_raw")),
        axis=1
    )

    df["daynight"] = df.get("src_daynight").fillna("").str.upper()
    df["type_code"] = pd.to_numeric(df.get("src_type"), errors="coerce").astype("Int8")
    df["version"] = df.get("src_version").astype(str)

    # --- Proyección EPSG:3035 ---
    valid_coords = df["latitude"].notna() & df["longitude"].notna()
    x_arr = np.full(len(df), np.nan, dtype=np.float64)
    y_arr = np.full(len(df), np.nan, dtype=np.float64)
    if valid_coords.any():
        lon_vals = df.loc[valid_coords, "longitude"].to_numpy(float)
        lat_vals = df.loc[valid_coords, "latitude"].to_numpy(float)
        x_proj, y_proj = TRANSFORMER.transform(lon_vals, lat_vals)
        x_arr[valid_coords.to_numpy()] = x_proj
        y_arr[valid_coords.to_numpy()] = y_proj
    df["x_3035"] = x_arr
    df["y_3035"] = y_arr

    # --- Celdas L0-L3 (anidamiento 2×2) ---
    # L0 = cell_size, L1 = 2*cell_size, L2 = 4*cell_size, L3 = 8*cell_size
    for level in range(4):
        level_cell_size = cell_size * (2 ** level)
        ix = np.floor(df["x_3035"] / level_cell_size).astype("Int64")
        iy = np.floor(df["y_3035"] / level_cell_size).astype("Int64")
        df[f"cell_id_L{level}"] = [
            format_cell_id(int(iy_v), int(ix_v), level, grid_prefix)
            if pd.notna(iy_v) and pd.notna(ix_v) else None
            for iy_v, ix_v in zip(iy, ix)
        ]

    # Parent_ids (basado en L0)
    parent_ids = []
    for _, row in df.iterrows():
        cell_id_l0 = row.get("cell_id_L0")
        if cell_id_l0 is None:
            parent_ids.append(None)
            continue
        try:
            parts = cell_id_l0.split(":")
            iy_v = int(parts[2][1:])
            ix_v = int(parts[3][1:])
            parent_ids.append(compute_parent_ids(iy_v, ix_v, grid_prefix))
        except Exception:
            parent_ids.append(None)
    df["parent_ids"] = parent_ids

    # --- observation_id determinista ---
    df["observation_id"] = (
        df["sensor"] + ":" + df["source_file"] + ":" + df["source_row"].astype(str)
    )

    # --- ingest_run_id (mismo para toda la corrida) ---
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Hash del primer archivo como identificador de corrida
    first_file = df["source_file"].iloc[0]
    first_hash = hashlib.sha256(first_file.encode()).hexdigest()[:8]
    ingest_run_id = f"{run_timestamp}-{first_hash}"
    df["ingest_run_id"] = ingest_run_id

    # --- flags ---
    df["flags"] = df.apply(
        lambda r: compute_flags(r, cell_size, partial_period_start),
        axis=1
    )

    return df


def select_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Selecciona y ordena columnas para el output contractual."""
    core_cols = [
        "observation_id",
        "sensor",
        "platform",
        "product",
        "acq_date",
        "acq_minute",
        "latitude",
        "longitude",
        "x_3035",
        "y_3035",
        "scan",
        "track",
        "frp",
        "brightness",
        "bright_t31",
        "confidence_raw",
        "confidence_rank",
        "daynight",
        "type_code",
        "version",
        "cell_id_L0",
        "cell_id_L1",
        "cell_id_L2",
        "cell_id_L3",
        "parent_ids",
        "flags",
        "ingest_run_id",
    ]

    src_cols = sorted([c for c in df.columns if c.startswith("src_")])
    internal = {"source_file", "source_row"}

    missing = [c for c in core_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas core en DataFrame: {missing}")

    final_cols = core_cols + src_cols
    return df[final_cols]


def validate_output(df: pd.DataFrame) -> None:
    """Validaciones contractuales obligatorias."""
    print("\n=== VALIDACIONES ===")
    print(f"Filas totales: {len(df)}")

    dup_ids = df["observation_id"].duplicated().sum()
    print(f"observation_id duplicados: {dup_ids}")
    if dup_ids > 0:
        raise ValueError(f"Hay {dup_ids} observation_id duplicados")

    dates = pd.to_datetime(df["acq_date"], errors="coerce")
    print(f"Rango fechas: {dates.min()} -> {dates.max()}")

    valid_coords = df["latitude"].notna() & df["longitude"].notna()
    print(f"Coordenadas válidas: {valid_coords.sum()} / {len(df)}")

    valid_proj = df["x_3035"].notna() & df["y_3035"].notna()
    print(f"Proyección válida: {valid_proj.sum()} / {len(df)}")

    has_cell = df["cell_id_L0"].notna().sum()
    print(f"Con cell_id_L0: {has_cell} / {len(df)}")

    print("Por sensor:")
    print(df["sensor"].value_counts().to_string())

    print("Por producto:")
    print(df["product"].value_counts().to_string())

    frp_sum = pd.to_numeric(df["frp"], errors="coerce").sum()
    print(f"FRP total: {frp_sum:.2f} MW")

    all_flags = []
    for fl in df["flags"]:
        if isinstance(fl, list):
            all_flags.extend(fl)
    if all_flags:
        from collections import Counter
        flag_counts = Counter(all_flags)
        print("Flags:")
        for flag, count in flag_counts.most_common():
            print(f"  {flag}: {count}")

    print("=== FIN VALIDACIONES ===\n")


def write_outputs(df: pd.DataFrame, parquet_path: Path, jsonl_path: Path) -> None:
    """Escribe Parquet y JSONL."""
    df.to_parquet(parquet_path, compression="zstd", index=False)
    print(f"Escrito Parquet: {parquet_path} ({parquet_path.stat().st_size / 1024:.1f} KB)")

    with jsonl_path.open("w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            rec = row.to_dict()
            for k, v in rec.items():
                if isinstance(v, (np.integer, np.floating)):
                    rec[k] = v.item() if not np.isnan(v) else None
                elif isinstance(v, np.ndarray):
                    rec[k] = v.tolist()
                elif isinstance(v, (pd.Timestamp, datetime)):
                    rec[k] = v.isoformat() if not pd.isna(v) else None
                elif isinstance(v, type(pd.NaT)):
                    rec[k] = None
                elif hasattr(v, 'isoformat'):
                    rec[k] = v.isoformat()
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Escrito JSONL: {jsonl_path} ({jsonl_path.stat().st_size / 1024:.1f} KB)")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fase 1: Proyección + Celdas (genérico)")
    p.add_argument("--input", nargs="+", type=Path, required=True,
                   help="Archivos JSON o directorios (recursivo)")
    p.add_argument("--output", type=Path, required=True,
                   help="Directorio de salida")
    p.add_argument("--cell-size", type=int, default=1000,
                   help="Tamaño de celda L0 en metros (default: 1000)")
    p.add_argument("--grid-prefix", type=str, default=None,
                   help="Prefijo grid ID (default: ES{size}K, ej. ES5K para 5000, ES1K para 1000)")
    p.add_argument("--partial-period-start", type=str, default=DEFAULT_PARTIAL_PERIOD_START,
                   help=f"Inicio de periodo incompleto (default: {DEFAULT_PARTIAL_PERIOD_START})")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    # Derivar grid_prefix si no se da
    if args.grid_prefix is None:
        size_km = args.cell_size // 1000
        args.grid_prefix = f"ES{size_km}K"

    # Calcular tamaños de celda por nivel
    cell_sizes = {level: args.cell_size * (2 ** level) for level in range(4)}

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = output_dir / "observations.parquet"
    jsonl_path = output_dir / "observations.jsonl"

    try:
        print("=== FASE 1: Proyección + Celdas ===")
        print(f"Cell size L0: {args.cell_size} m")
        print(f"Grid prefix: {args.grid_prefix}")
        print(f"Entradas: {[str(p) for p in args.input]}")
        print(f"Salida: {output_dir}")

        # 1. Recopilar archivos
        file_paths = collect_input_files(args.input)
        if not file_paths:
            raise RuntimeError("No se encontraron archivos JSON válidos")

        # 2. Cargar JSONs
        df = load_json_files(file_paths)

        # 3. Normalizar y enriquecer
        df = normalize_and_enrich(df, args.cell_size, args.grid_prefix, args.partial_period_start)

        # 4. Seleccionar columnas de output
        df = select_output_columns(df)

        # 5. Validar
        validate_output(df)

        # 6. Escribir
        write_outputs(df, parquet_path, jsonl_path)

        print("OK - FASE 1 completada correctamente")
        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())