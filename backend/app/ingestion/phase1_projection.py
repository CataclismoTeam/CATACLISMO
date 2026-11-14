#!/usr/bin/env python3
"""
Fase 1 — Proyección EPSG:3035 + Asignación a celdas L0–L3 (GENÉRICO)

Lee archivos JSON de FIRMS (MODIS/VIIRS, SP/NRT), aplica tipos, proyecta a EPSG:3035,
calcula celdas anidadas 2×2, añade control de calidad y trazabilidad,
y escribe observations.parquet + observations.json (array único).

Uso:
    python phase1_projection.py \
        --input /ruta/a/json1.json /ruta/a/directorio/ \
        --output ./output \
        --cell-size 1000 \
        --grid-prefix ES1K

Entrada: archivos JSON (array de objetos) o directorios (recursivo)
Salida: observations.parquet + observations.json (array único) en --output
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd
from pyproj import Transformer

# ---------------------------------------------------------------------------
# Configuración de logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("phase1_projection")

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

# Tamaño de chunk para streaming JSON (registros por batch)
STREAMING_CHUNK_SIZE = 10_000


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


def iter_json_records(file_path: Path, chunk_size: int = STREAMING_CHUNK_SIZE) -> Iterator[list[dict]]:
    """
    Itera sobre registros JSON en chunks para streaming.
    Soporta tanto array JSON como JSONL.
    """
    with file_path.open("r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return

        # Detectar formato: array JSON vs JSONL
        if content.startswith("["):
            # Array JSON - parsear completo (archivos FIRMS son pequeños)
            data = json.loads(content)
            if isinstance(data, list):
                for i in range(0, len(data), chunk_size):
                    yield data[i:i + chunk_size]
            else:
                logger.warning(f"{file_path.name}: JSON root no es array, se omite")
        else:
            # JSONL - parsear línea a línea
            chunk = []
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk.append(json.loads(line))
                    if len(chunk) >= chunk_size:
                        yield chunk
                        chunk = []
                except json.JSONDecodeError as e:
                    logger.warning(f"Línea JSON inválida en {file_path.name}: {e}")
            if chunk:
                yield chunk


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
            logger.warning(f"{path} no existe o no es .json/.directorio, se omite")
    return files


def load_json_files(file_paths: list[Path]) -> pd.DataFrame:
    """Carga múltiples JSON y devuelve DataFrame combinado con columnas src_*."""
    all_records = []
    file_hashes = {}

    for fpath in file_paths:
        file_hashes[fpath.name] = compute_file_hash(fpath)

        # Streaming por chunks
        for chunk in iter_json_records(fpath):
            for idx, record in enumerate(chunk):
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
    logger.info(f"Cargados {len(df)} registros de {len(file_hashes)} archivos")
    for fname, h in file_hashes.items():
        logger.info(f"  {fname}: sha256={h[:16]}...")
    return df


def normalize_and_enrich(
    df: pd.DataFrame,
    cell_size: float,
    grid_prefix: str,
    partial_period_start: str,
    file_paths: list[Path]
) -> pd.DataFrame:
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
    for level in range(4):
        level_cell_size = cell_size * (2 ** level)
        ix = np.floor(df["x_3035"] / level_cell_size).astype("Int64")
        iy = np.floor(df["y_3035"] / level_cell_size).astype("Int64")
        df[f"cell_id_L{level}"] = [
            f"{grid_prefix}:L{level}:Y{int(iy_v):05d}:X{int(ix_v):05d}"
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
            parent_ids.append({
                f"L{level}": f"{grid_prefix}:L{level}:Y{iy_v // (2**level):05d}:X{ix_v // (2**level):05d}"
                for level in (1, 2, 3)
            })
        except Exception:
            parent_ids.append(None)
    df["parent_ids"] = parent_ids

    # --- observation_id determinista ---
    df["observation_id"] = (
        df["sensor"] + ":" + df["source_file"] + ":" + df["source_row"].astype(str)
    )

    # --- ingest_run_id (mismo para toda la corrida) ---
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Usar el hash del primer archivo real, no el nombre
    first_file_name = df["source_file"].iloc[0]
    first_file_path = None
    for fpath in file_paths:
        if fpath.name == first_file_name:
            first_file_path = fpath
            break
    first_hash = compute_file_hash(first_file_path)[:8] if first_file_path else hashlib.sha256(first_file_name.encode()).hexdigest()[:8]
    ingest_run_id = f"{run_timestamp}-{first_hash}"
    df["ingest_run_id"] = ingest_run_id

    # --- flags ---
    df["flags"] = df.apply(
        lambda r: compute_flags(r, cell_size, partial_period_start),
        axis=1
    )

    return df


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
            if float(x_3035) < 2_500_000:
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
    """Formatea cell_id: {grid_prefix}:L{level}:Y{iy}:X{ix}."""
    return f"{grid_prefix}:L{level}:Y{iy:05d}:X{ix:05d}"


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
    logger.info("\n=== VALIDACIONES ===")
    logger.info(f"Filas totales: {len(df)}")

    dup_ids = df["observation_id"].duplicated().sum()
    logger.info(f"observation_id duplicados: {dup_ids}")
    if dup_ids > 0:
        raise ValueError(f"Hay {dup_ids} observation_id duplicados")

    dates = pd.to_datetime(df["acq_date"], errors="coerce")
    logger.info(f"Rango fechas: {dates.min()} -> {dates.max()}")

    valid_coords = df["latitude"].notna() & df["longitude"].notna()
    logger.info(f"Coordenadas válidas: {valid_coords.sum()} / {len(df)}")

    valid_proj = df["x_3035"].notna() & df["y_3035"].notna()
    logger.info(f"Proyección válida: {valid_proj.sum()} / {len(df)}")

    has_cell = df["cell_id_L0"].notna().sum()
    logger.info(f"Con cell_id_L0: {has_cell} / {len(df)}")

    logger.info("Por sensor:")
    logger.info(df["sensor"].value_counts().to_string())

    logger.info("Por producto:")
    logger.info(df["product"].value_counts().to_string())

    frp_sum = pd.to_numeric(df["frp"], errors="coerce").sum()
    logger.info(f"FRP total: {frp_sum:.2f} MW")

    all_flags = []
    for fl in df["flags"]:
        if isinstance(fl, list):
            all_flags.extend(fl)
    if all_flags:
        from collections import Counter
        flag_counts = Counter(all_flags)
        logger.info("Flags:")
        for flag, count in flag_counts.most_common():
            logger.info(f"  {flag}: {count}")

    logger.info("=== FIN VALIDACIONES ===\n")


def write_outputs(df: pd.DataFrame, parquet_path: Path, json_path: Path) -> None:
    """Escribe Parquet y JSON (array único)."""
    df.to_parquet(parquet_path, compression="zstd", index=False)
    logger.info(f"Escrito Parquet: {parquet_path} ({parquet_path.stat().st_size / 1024:.1f} KB)")

    from json_output import JSONArrayWriter

    with JSONArrayWriter(json_path, indent=2) as w:
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
            w.write(rec)
    logger.info(f"Escrito JSON: {json_path} ({json_path.stat().st_size / 1024:.1f} KB)")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fase 1: Proyección + Celdas (GENÉRICO)")
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
    p.add_argument("--chunk-size", type=int, default=10000,
                   help="Tamaño de chunk para streaming JSON (default: 10000)")
    p.add_argument("--validate-only", action="store_true",
                   help="Solo valida archivo existente sin reprocesar")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    # Derivar grid_prefix si no se da
    if args.grid_prefix is None:
        size_km = args.cell_size // 1000
        args.grid_prefix = f"ES{size_km}K"

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    parquet_path = output_dir / "observations.parquet"
    json_path = output_dir / "observations.json"

    try:
        logger.info("=== FASE 1: Proyección + Celdas ===")
        logger.info(f"Cell size L0: {args.cell_size} m")
        logger.info(f"Grid prefix: {args.grid_prefix}")
        logger.info(f"Entradas: {[str(p) for p in args.input]}")
        logger.info(f"Salida: {output_dir}")

        # Validación solo
        if args.validate_only:
            if not parquet_path.exists():
                raise FileNotFoundError(f"No existe {parquet_path}")
            df = pd.read_parquet(parquet_path)
            validate_output(df)
            logger.info("Validación OK")
            return 0

        # 1. Recopilar archivos
        file_paths = collect_input_files(args.input)
        if not file_paths:
            raise RuntimeError("No se encontraron archivos JSON válidos")

        # 2. Cargar JSONs
        df = load_json_files(file_paths)

        # 3. Normalizar y enriquecer
        df = normalize_and_enrich(df, args.cell_size, args.grid_prefix, args.partial_period_start, file_paths)

        # 4. Seleccionar columnas de output
        df = select_output_columns(df)

        # 5. Validar
        validate_output(df)

        # 6. Escribir
        write_outputs(df, parquet_path, json_path)

        logger.info("OK - FASE 1 completada correctamente")
        return 0

    except Exception as e:
        logger.error(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())