"""Parser de observaciones FIRMS (MODIS y VIIRS).

Lee archivos con la estructura de los extractos FIRMS, identifica el sensor a
partir de evidencia presente en el propio archivo, normaliza los nombres de las
columnas principales y escribe un único CSV con todas las observaciones y su
procedencia.

No armoniza sensores, no construye rejillas, no deduplica ni corrige datos. Los
archivos de origen se abren en modo lectura y nunca se modifican.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #

# Extensiones que esta versión sabe leer. El resto se informa como omitido.
READABLE_SUFFIXES = {".json", ".jsonl", ".ndjson", ".csv"}

# Campo de origen -> nombre normalizado. Se compara en minúsculas y sin espacios.
# Gana la primera coincidencia, así que el orden importa.
FIELD_MAP: list[tuple[str, str]] = [
    ("latitude", "latitude"),
    ("lat", "latitude"),
    ("longitude", "longitude"),
    ("lon", "longitude"),
    ("lng", "longitude"),
    ("acq_date", "acquisition_date"),
    ("acquisition_date", "acquisition_date"),
    ("acq_time", "acquisition_time"),
    ("acquisition_time", "acquisition_time"),
    ("satellite", "satellite"),
    ("platform", "satellite"),
    ("instrument", "instrument"),
    ("sensor", "instrument"),
    ("confidence", "confidence"),
    ("frp", "frp"),
    ("brightness", "brightness_temperature"),
    ("bright_ti4", "brightness_temperature"),
    ("brightness_temperature", "brightness_temperature"),
]

# Campos que todo registro de salida lleva (vacíos cuando el origen no los trae).
CORE_COLUMNS = [
    "observation_id",
    "sensor",
    "satellite",
    "instrument",
    "acquisition_datetime",
    "acquisition_date",
    "acquisition_time",
    "latitude",
    "longitude",
    "confidence",
    "frp",
    "brightness_temperature",
    "source_file",
    "source_product",
    "source_format",
    "source_row",
    "identification_basis",
]

# Nombres de satélite que identifican cada sensor sin ambigüedad.
MODIS_SATELLITES = {"TERRA", "AQUA"}
VIIRS_SATELLITES = {"SNPP", "NPP", "NOAA-20", "NOAA-21", "JPSS-1", "JPSS-2", "VIIRS"}

# Directorios de proyecto que nunca contienen datos de entrada.
SKIP_DIR_NAMES = {"__pycache__", ".git", "output", ".venv", "venv", "node_modules"}


# --------------------------------------------------------------------------- #
# Descubrimiento y lectura
# --------------------------------------------------------------------------- #


def collect_files(inputs: list[Path]) -> tuple[list[Path], list[Path]]:
    """Devuelve los archivos encontrados y las rutas que no existen.

    Cada ruta de entrada puede ser un archivo o una carpeta (se recorre entera).
    """
    found: list[Path] = []
    missing: list[Path] = []
    for item in inputs:
        if item.is_file():
            found.append(item)
        elif item.is_dir():
            found.extend(p for p in item.rglob("*") if p.is_file())
        else:
            missing.append(item)
    return sorted(set(found)), missing


def is_skipped(path: Path, output_dir: Path) -> bool:
    if output_dir in path.parents:
        return True
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def read_records(path: Path) -> tuple[list[dict[str, Any]], str, str | None]:
    """Lee un archivo y devuelve (registros, formato, motivo_de_omisión).

    El motivo es None cuando la lectura fue correcta.
    """
    suffix = path.suffix.lower()

    if suffix in {".json", ".jsonl", ".ndjson"}:
        try:
            if suffix in {".jsonl", ".ndjson"}:
                lines = path.read_text(encoding="utf-8").splitlines()
                records = [json.loads(line) for line in lines if line.strip()]
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, list):
                    kind = type(payload).__name__
                    return [], "json", f"el JSON de nivel superior es {kind}, no una lista"
                records = payload
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return [], "json", f"JSON ilegible: {exc.__class__.__name__}"

        if not records:
            return [], "json", "la lista de registros está vacía"
        if not all(isinstance(record, dict) for record in records):
            return [], "json", "la lista contiene elementos que no son objetos"
        fmt = "jsonl" if suffix in {".jsonl", ".ndjson"} else "json"
        return records, fmt, None

    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            records = list(csv.DictReader(handle))
        if not records:
            return [], "csv", "CSV vacío"
        return records, "csv", None

    return [], "unknown", f"extensión '{suffix}' no soportada"


def has_coordinates(records: list[dict[str, Any]]) -> bool:
    keys = {str(key).strip().lower() for key in records[0]}
    return bool(keys & {"latitude", "lat"}) and bool(keys & {"longitude", "lon", "lng"})


# --------------------------------------------------------------------------- #
# Identificación
# --------------------------------------------------------------------------- #


def identify_sensor(filename: str, first: dict[str, Any]) -> tuple[str, str]:
    """Identifica MODIS o VIIRS solo con evidencia del archivo.

    Si la evidencia es contradictoria devuelve 'unknown' y explica el conflicto.
    """
    low = {str(key).strip().lower(): value for key, value in first.items()}
    name = filename.upper()
    instrument = str(low.get("instrument", "")).strip().upper()
    satellite = str(low.get("satellite", "")).strip().upper()
    version = str(low.get("version", "")).strip().upper()

    modis: list[str] = []
    viirs: list[str] = []

    if "M-C6" in name:
        modis.append("el nombre del archivo contiene 'M-C6'")
    if instrument == "MODIS":
        modis.append("instrument == 'MODIS'")
    if re.match(r"^6(\.|$)", version):
        modis.append(f"version == '{low.get('version')}'")
    if satellite in MODIS_SATELLITES:
        modis.append(f"satellite == '{low.get('satellite')}'")

    if "V-C2" in name:
        viirs.append("el nombre del archivo contiene 'V-C2'")
    if instrument in VIIRS_SATELLITES:
        viirs.append(f"instrument == '{low.get('instrument')}'")
    if version in {"2", "2.0NRT"}:
        viirs.append(f"version == '{low.get('version')}'")
    if satellite in VIIRS_SATELLITES:
        viirs.append(f"satellite == '{low.get('satellite')}'")

    if modis and viirs:
        conflict = "; ".join(modis + viirs)
        return "unknown", f"evidencia contradictoria: {conflict}"
    if modis:
        return "MODIS", "; ".join(modis)
    if viirs:
        return "VIIRS", "; ".join(viirs)
    return "unknown", "sin evidencia identificatoria"


def identify_product(filename: str, first: dict[str, Any]) -> str:
    low = {str(key).strip().lower(): value for key, value in first.items()}
    name = filename.lower()
    version = str(low.get("version", "")).upper()

    if "archive" in name:
        return "SP"
    if "nrt" in name or "NRT" in version:
        return "NRT"
    return "unknown"


# --------------------------------------------------------------------------- #
# Normalización
# --------------------------------------------------------------------------- #


def build_datetime(date_raw: Any, time_raw: Any) -> tuple[str | None, str | None]:
    """Devuelve (fecha ISO, problema). Sin valores inventados: si falla, None."""
    if date_raw is None:
        return None, "falta la fecha"

    try:
        day = datetime.strptime(str(date_raw).strip(), "%Y-%m-%d")
    except ValueError:
        return None, "fecha no interpretable"

    if time_raw is None:
        return None, "falta la hora"

    time_text = str(time_raw).strip()
    if not re.fullmatch(r"\d{1,4}", time_text):
        return None, "hora no interpretable"

    time_text = time_text.zfill(4)
    hours, minutes = int(time_text[:2]), int(time_text[2:])
    if hours > 23 or minutes > 59:
        return None, "hora fuera de rango"

    merged = day.replace(hour=hours, minute=minutes)
    return merged.strftime("%Y-%m-%dT%H:%M:%S"), None


def normalize_record(
    record: dict[str, Any], meta: dict[str, Any], row_number: int
) -> tuple[dict[str, Any], str | None]:
    low = {str(key).strip().lower(): value for key, value in record.items()}

    row: dict[str, Any] = {
        "observation_id": f"{meta['stem']}#{row_number}",
        "sensor": meta["sensor"],
        "source_file": meta["source_file"],
        "source_product": meta["product"],
        "source_format": meta["format"],
        "source_row": row_number,
        "identification_basis": meta["basis"] or None,
    }

    filled: set[str] = set()
    for source_key, target in FIELD_MAP:
        if target in filled or source_key not in low:
            continue
        row[target] = low[source_key]
        filled.add(target)

    iso, problem = build_datetime(
        low.get("acq_date", low.get("acquisition_date")),
        low.get("acq_time", low.get("acquisition_time")),
    )
    row["acquisition_datetime"] = iso

    # Todo campo original se conserva intacto con el prefijo src_.
    for key, value in record.items():
        row[f"src_{str(key).strip()}"] = value

    return row, problem


def unique_stems(paths: list[Path]) -> dict[Path, str]:
    """Evita colisiones de observation_id cuando dos archivos comparten nombre."""
    counts = Counter(path.stem for path in paths)
    seen: Counter[str] = Counter()
    stems: dict[Path, str] = {}
    for path in paths:
        if counts[path.stem] == 1:
            stems[path] = path.stem
        else:
            seen[path.stem] += 1
            stems[path] = f"{path.stem}-{seen[path.stem]}"
    return stems


# --------------------------------------------------------------------------- #
# Resumen
# --------------------------------------------------------------------------- #


def append_counts(lines: list[str], df: pd.DataFrame, column: str, title: str) -> None:
    if column not in df.columns:
        lines.append(f"{title}: columna ausente")
        return
    lines.append(f"{title}:")
    values = df[column].fillna("(vacío)")
    for value, count in values.value_counts().items():
        lines.append(f"  {str(value):<20} {count:>7,}")


def describe(
    df: pd.DataFrame,
    skipped: list[tuple[str, str]],
    scanned: list[str],
    total_read: int,
    problems: dict[str, int],
) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("RESUMEN DEL PARSER")
    lines.append("=" * 72)
    lines.append("Entradas escaneadas:")
    lines.extend(f"  {item}" for item in scanned)
    lines.append("")

    lines.append(f"Archivos procesados: {df['source_file'].nunique()}")
    for name, count in df["source_file"].value_counts().items():
        subset = df[df["source_file"] == name]
        sensor = subset["sensor"].iloc[0]
        product = subset["source_product"].iloc[0]
        lines.append(f"  OK   {name:<44} {count:>7,} filas  {sensor} {product}")

    lines.append(f"Archivos omitidos: {len(skipped)}")
    for name, reason in skipped:
        lines.append(f"  SKIP {name:<44} {reason}")

    lines.append("")
    lines.append(f"Total de observaciones: {len(df):,}")
    lines.append(f"Filas leídas de los orígenes: {total_read:,} (escritas: {len(df):,})")
    lines.append("")

    append_counts(lines, df, "sensor", "Observaciones por sensor")
    append_counts(lines, df, "satellite", "Observaciones por satélite")
    append_counts(lines, df, "source_product", "Observaciones por producto")
    append_counts(lines, df, "source_format", "Observaciones por formato de origen")

    lines.append("")
    normalized = [c for c in df.columns if not c.startswith("src_")]
    preserved = [c for c in df.columns if c.startswith("src_")]
    lines.append(f"Columnas en la salida: {len(df.columns)}")
    lines.append(f"  normalizadas ({len(normalized)}): {', '.join(normalized)}")
    lines.append(f"  originales conservadas ({len(preserved)}): {', '.join(preserved)}")

    lines.append("")
    lines.append("Filas con valores ausentes en columnas normalizadas:")
    any_missing = 0
    for column in normalized:
        missing = int(df[column].isna().sum())
        if missing:
            lines.append(f"  {column:<24} {missing:>7,} filas ({100 * missing / len(df):5.1f}%)")
    present = [c for c in normalized if not c.startswith(("source_", "identification"))]
    if present:
        any_missing = int(df[present].isna().any(axis=1).sum())
    lines.append(f"  filas con al menos un valor ausente: {any_missing:,}")

    lines.append("")
    if "acquisition_date" in df.columns:
        dates = df["acquisition_date"].dropna().astype(str)
        if len(dates):
            lines.append(f"Rango de fechas: {dates.min()} -> {dates.max()}")
        else:
            lines.append("Rango de fechas: sin fechas interpretadas")
    else:
        lines.append("Rango de fechas: columna ausente")

    if "acquisition_datetime" in df.columns:
        parsed = int(df["acquisition_datetime"].notna().sum())
        lines.append(f"Fecha y hora interpretadas: {parsed:,} de {len(df):,}")
    if problems:
        detail = ", ".join(f"{key}={value}" for key, value in sorted(problems.items()))
        lines.append(f"Problemas de fecha u hora: {detail}")

    lines.append("")
    lines.append("Límites geográficos:")
    for column in ("latitude", "longitude"):
        if column not in df.columns:
            lines.append(f"  {column:<10} columna ausente")
            continue
        values = pd.to_numeric(df[column], errors="coerce")
        invalid = int(values.isna().sum())
        lines.append(
            f"  {column:<10} {values.min():.5f} .. {values.max():.5f} "
            f"(no numéricos o vacíos: {invalid})"
        )
    if {"latitude", "longitude"} <= set(df.columns):
        lat = pd.to_numeric(df["latitude"], errors="coerce")
        lon = pd.to_numeric(df["longitude"], errors="coerce")
        outside = int(((lat.abs() > 90) | (lon.abs() > 180)).sum())
        lines.append(f"  coordenadas fuera de rango válido: {outside}")

    lines.append("")
    duplicate_keys = ["latitude", "longitude", "acquisition_date", "acquisition_time"]
    duplicate_keys.append("satellite" if "satellite" in df.columns else "sensor")
    if set(duplicate_keys) <= set(df.columns):
        duplicates = int(df.duplicated(subset=duplicate_keys).sum())
        lines.append(f"Detecciones duplicadas exactas: {duplicates:,} (solo se informan)")
    else:
        lines.append("Detecciones duplicadas exactas: no calculable (faltan columnas)")

    lines.append("")
    lines.append(f"observation_id duplicados: {int(df['observation_id'].duplicated().sum()):,}")
    lines.append("=" * 72)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Principal
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Parser de observaciones FIRMS")
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        default=[script_dir / "input"],
        help="archivos o carpetas de origen (por defecto: parser/input)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=script_dir / "output",
        help="carpeta de salida (por defecto: parser/output)",
    )
    args = parser.parse_args(argv)

    inputs = [item.resolve() for item in args.input]
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates, missing = collect_files(inputs)
    for item in missing:
        print(f"Aviso: la ruta no existe y se omite: {item}", file=sys.stderr)
    if not candidates:
        print("No se encontraron archivos de entrada.", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []
    problems: dict[str, int] = {}
    total_read = 0
    accepted: list[tuple[Path, list[dict[str, Any]], str]] = []

    for path in candidates:
        if is_skipped(path, output_dir):
            continue
        if path.suffix.lower() not in READABLE_SUFFIXES:
            skipped.append((path.name, f"extensión '{path.suffix}' no soportada"))
            continue

        records, fmt, reason = read_records(path)
        if reason:
            skipped.append((path.name, reason))
            continue
        if not has_coordinates(records):
            skipped.append((path.name, "sin latitude/longitude: no es una tabla de puntos"))
            continue
        accepted.append((path, records, fmt))

    stems = unique_stems([path for path, _, _ in accepted])

    for path, records, fmt in accepted:
        sensor, basis = identify_sensor(path.name, records[0])
        meta = {
            "stem": stems[path],
            "source_file": path.name,
            "sensor": sensor,
            "product": identify_product(path.name, records[0]),
            "format": fmt,
            "basis": basis,
        }

        total_read += len(records)
        for index, record in enumerate(records, start=1):
            row, problem = normalize_record(record, meta, index)
            rows.append(row)
            if problem:
                problems[problem] = problems.get(problem, 0) + 1

    if not rows:
        print("No hay archivos compatibles con la estructura esperada.", file=sys.stderr)
        for name, reason in skipped:
            print(f"  SKIP {name}: {reason}", file=sys.stderr)
        return 1

    df = pd.DataFrame(rows)
    ordered = [column for column in CORE_COLUMNS if column in df.columns]
    ordered += [c for c in df.columns if c not in ordered and not c.startswith("src_")]
    ordered += sorted(c for c in df.columns if c.startswith("src_"))
    df = df[ordered]

    csv_path = output_dir / "parsed_data.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig", na_rep="")

    report = describe(df, skipped, [str(item) for item in inputs], total_read, problems)
    print(report)
    print(f"Escrito: {csv_path} ({csv_path.stat().st_size:,} bytes)")

    if total_read != len(df):
        print(
            f"CONTABILIDAD DE FILAS ROTA: leídas {total_read}, escritas {len(df)}", file=sys.stderr
        )
        return 3
    if not df["observation_id"].is_unique:
        print("observation_id repetido: revisa nombres de archivo.", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
