"""Lectura y validación de los JSON de FIRMS, y filtros previos a la armonización."""

import json
from datetime import date
from pathlib import Path

import polars as pl

from .config import Config

VIIRS_INSTRUMENTS = {"VIIRS", "SNPP", "NOAA20", "NOAA21", "N20", "N21"}

SCHEMA = {
    "lat": pl.Float64,
    "lon": pl.Float64,
    "date": pl.Date,
    "minute": pl.Int16,
    "sensor": pl.String,
    "satellite": pl.String,
    "quality": pl.String,
    "conf": pl.String,
    "conf_num": pl.Int16,
    "type": pl.Int8,
    "frp": pl.Float64,
    "daynight": pl.String,
}


class DiscardLog:
    """Registro de cuántas detecciones se descartan en cada paso y por qué."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def add(self, step: str, sensor: str, count: int) -> None:
        if count:
            self.rows.append({"paso": step, "sensor": sensor, "descartadas": count})

    def total(self) -> int:
        return sum(int(r["descartadas"]) for r in self.rows)


def _confidence(sensor: str, raw: object) -> tuple[str, int | None]:
    """Clase común l/n/h. MODIS: < 30 baja, 30-79 nominal, >= 80 alta (clases de FIRMS)."""
    if sensor == "MODIS":
        value = int(str(raw))
        if not 0 <= value <= 100:
            raise ValueError("confianza fuera de 0-100")
        return ("l" if value < 30 else "n" if value < 80 else "h"), value
    cls = str(raw).strip().lower()[:1]
    if cls not in {"l", "n", "h"}:
        raise ValueError("confianza VIIRS desconocida")
    return cls, None


def _parse(rec: dict[str, object]) -> tuple:
    lat = float(rec["latitude"])  # type: ignore[arg-type]
    lon = float(rec["longitude"])  # type: ignore[arg-type]
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("coordenadas fuera de rango")
    day = date.fromisoformat(str(rec["acq_date"]))
    hhmm = str(rec["acq_time"]).zfill(4)
    hour, minute = int(hhmm[:2]), int(hhmm[2:])
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("hora no válida")
    instrument = str(rec["instrument"]).upper()
    if instrument == "MODIS":
        sensor = "MODIS"
    elif instrument in VIIRS_INSTRUMENTS:
        sensor = "VIIRS"
    else:
        raise ValueError("instrumento desconocido")
    conf, conf_num = _confidence(sensor, rec["confidence"])
    quality = "nrt" if "RT" in str(rec["version"]).upper() else "std"
    kind = rec.get("type")
    frp = float(rec["frp"])  # type: ignore[arg-type]
    if frp < 0:
        raise ValueError("FRP negativa")
    return (
        lat,
        lon,
        day,
        hour * 60 + minute,
        sensor,
        str(rec["satellite"]),
        quality,
        conf,
        conf_num,
        None if kind is None else int(str(kind)),
        frp,
        str(rec.get("daynight", "")),
    )


def read_records(paths: list[Path], log: DiscardLog) -> pl.DataFrame:
    """Lee los JSON de FIRMS a una tabla única con columnas comunes y campo `sensor`."""
    rows: list[tuple] = []
    invalid = 0
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            records = json.load(fh)
        if not isinstance(records, list):
            raise ValueError(f"{path}: se esperaba una lista de detecciones")
        for rec in records:
            try:
                rows.append(_parse(rec))
            except (KeyError, TypeError, ValueError):
                invalid += 1
    log.add("registro no válido (esquema, rango o fecha)", "todos", invalid)
    return pl.DataFrame(rows, schema=SCHEMA, orient="row")


def find_inputs(root: Path) -> list[Path]:
    paths = sorted(root.rglob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No hay ficheros JSON de FIRMS en {root}")
    return paths


def _keep(df: pl.DataFrame, mask: pl.Expr, step: str, log: DiscardLog) -> pl.DataFrame:
    kept = df.filter(mask)
    before = dict(df.group_by("sensor").len().iter_rows())
    after = dict(kept.group_by("sensor").len().iter_rows())
    for sensor in sorted(before):
        log.add(step, sensor, before[sensor] - after.get(sensor, 0))
    return kept


def apply_filters(df: pl.DataFrame, cfg: Config, log: DiscardLog) -> pl.DataFrame:
    """Recorte al área, empalme archivo + NRT sin duplicados, y filtros de tipo y confianza."""
    g = cfg.grid
    df = _keep(
        df,
        (pl.col("lon") >= g.west)
        & (pl.col("lon") < g.east)
        & (pl.col("lat") >= g.south)
        & (pl.col("lat") < g.north),
        "fuera del área",
        log,
    )

    # Duplicados exactos: se conserva el procesado estándar frente al NRT
    key = ["lat", "lon", "date", "minute", "satellite"]
    unique = df.sort("quality", descending=True, maintain_order=True).unique(
        subset=key, keep="first", maintain_order=True
    )
    before = dict(df.group_by("sensor").len().iter_rows())
    after = dict(unique.group_by("sensor").len().iter_rows())
    for sensor in sorted(before):
        log.add("duplicada", sensor, before[sensor] - after.get(sensor, 0))
    df = unique

    # Empalme: el NRT solo cuenta a partir del día siguiente al último del archivo estándar
    last_std = (
        df.filter(pl.col("quality") == "std")
        .group_by("sensor")
        .agg(pl.col("date").max().alias("last_std"))
    )
    df = df.join(last_std, on="sensor", how="left")
    df = _keep(
        df,
        (pl.col("quality") == "std")
        | pl.col("last_std").is_null()
        | (pl.col("date") > pl.col("last_std")),
        "NRT ya cubierto por el archivo estándar",
        log,
    ).drop("last_std")

    # Máscara de fuentes estáticas para el NRT, que no trae "type"
    excluded = df.filter(pl.col("type").is_not_null() & ~pl.col("type").is_in(cfg.types))
    step = cfg.static_mask_deg
    bin_cols = [
        (pl.col("lat") / step).floor().cast(pl.Int32).alias("bin_lat"),
        (pl.col("lon") / step).floor().cast(pl.Int32).alias("bin_lon"),
    ]
    mask_bins = (
        excluded.with_columns(bin_cols)
        .group_by("bin_lat", "bin_lon")
        .len()
        .filter(pl.col("len") >= cfg.static_mask_min)
        .select("bin_lat", "bin_lon", pl.lit(True).alias("static"))
    )

    df = _keep(
        df,
        pl.col("type").is_null() | pl.col("type").is_in(cfg.types),
        "tipo excluido (volcán, fuente estática u offshore)",
        log,
    )
    df = df.with_columns(bin_cols).join(mask_bins, on=["bin_lat", "bin_lon"], how="left")
    df = _keep(
        df,
        pl.col("type").is_not_null() | pl.col("static").is_null(),
        "NRT sobre fuente estática conocida",
        log,
    ).drop("bin_lat", "bin_lon", "static")

    low = (pl.col("sensor") == "MODIS") & (pl.col("conf_num") < cfg.modis_min_confidence)
    if cfg.viirs_drop_low:
        low = low | ((pl.col("sensor") == "VIIRS") & (pl.col("conf") == "l"))
    return _keep(df, ~low, "confianza baja", log)
