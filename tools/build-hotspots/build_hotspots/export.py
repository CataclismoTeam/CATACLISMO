"""Escritura de los agregados que lee la web: manifiesto JSON + binarios tipados por año.

Formato de `hotspots-grid-v1-<año>.bin` (little-endian, n = entradas del año, sin cabecera;
n viene en el manifiesto). Estructura de arrays, de mayor a menor alineación:

    Float32[n]  h       conteo armonizado (detecciones equivalentes MODIS)
    Float32[n]  frpM    suma de FRP de MODIS (MW)
    Float32[n]  frpV    suma de FRP de VIIRS (MW)
    Uint16[n]   cell    índice en hotspots-cells-v1.bin
    Uint16[n]   m       detecciones MODIS (conteo bruto tras filtros)
    Uint16[n]   v       detecciones VIIRS (conteo bruto tras filtros)
    Uint8[n]    month   mes del año, 0-11

`hotspots-cells-v1.bin` es un Uint32[] con el identificador global de cada celda con datos
(fila * ncols + columna, fila 0 al sur y columna 0 al oeste).
"""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from . import FORMAT_VERSION
from .config import Config
from .harmonize import Harmonized
from .ingest import DiscardLog

V = f"v{FORMAT_VERSION}"
MANIFEST = f"hotspots-manifest-{V}.json"
CELLS = f"hotspots-cells-{V}.bin"
RECENT = f"detections-recent-{V}.json"
# El guardián del repo rechaza ficheros versionados de más de 1024 KB
MAX_FILE_KB = 1024

ATTRIBUTION = (
    "NASA FIRMS / LANCE: MODIS Collection 6.1 (Terra y Aqua) y VIIRS S-NPP 375 m Collection 2. "
    "Datos de acceso libre; NASA no avala este producto."
)


def grid_file(year: int) -> str:
    return f"hotspots-grid-{V}-{year}.bin"


def _write(out: Path, name: str, payload: bytes) -> dict[str, object]:
    if len(payload) > MAX_FILE_KB * 1024:
        raise ValueError(f"{name} ocupa {len(payload) // 1024} KB (máximo {MAX_FILE_KB} KB)")
    (out / name).write_bytes(payload)
    return {"fichero": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def _recent(df: pl.DataFrame, cfg: Config) -> dict[str, object]:
    last = df["date"].max()
    since = last - timedelta(days=cfg.recent_days - 1)
    rows = df.filter(pl.col("date") >= since).sort("date", "minute")
    epoch = [
        int(datetime.combine(d, time(m // 60, m % 60), tzinfo=UTC).timestamp())
        for d, m in zip(rows["date"], rows["minute"], strict=True)
    ]
    return {
        "desde": since.isoformat(),
        "hasta": last.isoformat(),
        "campos": {
            "t": "segundos Unix (UTC)",
            "sensor": ["MODIS", "VIIRS"],
            "conf": ["baja", "nominal", "alta"],
            "frp": "MW",
            "noche": "1 = paso nocturno",
            "provisional": "1 = dato NRT sin consolidar",
        },
        "lat": [round(x, 4) for x in rows["lat"]],
        "lon": [round(x, 4) for x in rows["lon"]],
        "t": epoch,
        "sensor": [0 if s == "MODIS" else 1 for s in rows["sensor"]],
        "conf": ["lnh".index(c) for c in rows["conf"]],
        "frp": [round(x, 1) for x in rows["frp"]],
        "noche": [1 if d == "N" else 0 for d in rows["daynight"]],
        "provisional": [1 if q == "nrt" else 0 for q in rows["quality"]],
    }


def write_outputs(
    out: Path,
    df: pl.DataFrame,
    result: Harmonized,
    cfg: Config,
    log: DiscardLog,
    read_count: int,
    generated: str,
) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    cells = result.cells
    gids = np.sort(cells["gid"].unique().to_numpy()).astype("<u4")
    if len(gids) > np.iinfo(np.uint16).max:
        raise ValueError("Demasiadas celdas con datos para un índice de 16 bits")
    if max(cells["m"].max(), cells["v"].max()) > np.iinfo(np.uint16).max:
        raise ValueError("Un conteo mensual por celda no cabe en 16 bits")

    files = [_write(out, CELLS, gids.tobytes())]
    cell_idx = np.searchsorted(gids, cells["gid"].to_numpy())
    cells = cells.with_columns(pl.Series("cell", cell_idx, dtype=pl.UInt16))

    years = []
    for y in range(result.n_months // 12):
        part = cells.filter(pl.col("mi") // 12 == y)
        payload = b"".join(
            [
                part["h"].to_numpy().astype("<f4").tobytes(),
                part["frp_m"].to_numpy().astype("<f4").tobytes(),
                part["frp_v"].to_numpy().astype("<f4").tobytes(),
                part["cell"].to_numpy().astype("<u2").tobytes(),
                part["m"].to_numpy().astype("<u2").tobytes(),
                part["v"].to_numpy().astype("<u2").tobytes(),
                (part["mi"].to_numpy() % 12).astype("u1").tobytes(),
            ]
        )
        year = result.start_year + y
        years.append(
            {"anio": year, "entradas": part.height, **_write(out, grid_file(year), payload)}
        )

    recent = _recent(df, cfg)
    files.append(_write(out, RECENT, json.dumps(recent, separators=(",", ":")).encode("utf-8")))

    grid = cfg.grid
    manifest = {
        "version": FORMAT_VERSION,
        "generado": generated,
        "fuente": ATTRIBUTION,
        "productos": {
            "MODIS": "MODIS Collection 6.1, Terra y Aqua, 1 km (archivo estándar + NRT)",
            "VIIRS": "VIIRS S-NPP Collection 2, 375 m (archivo estándar + NRT)",
        },
        "rejilla": {
            "oeste": grid.west,
            "sur": grid.south,
            "este": grid.east,
            "norte": grid.north,
            "celdaGrados": grid.cell_deg,
            "columnas": grid.ncols,
            "filas": grid.nrows,
            "celdasConDatos": int(len(gids)),
        },
        "tiempo": {
            "anioInicial": result.start_year,
            "meses": result.n_months,
            "ultimoDato": df["date"].max().isoformat(),
            "primerDato": df["date"].min().isoformat(),
            "sensores": result.sensor_ranges,
            "diasDelMes": result.days_in_month,
            "diasCubiertos": result.days_covered,
            # bit 1 = MODIS con NRT, bit 2 = VIIRS con NRT
            "provisional": result.provisional,
            "usadoParaCalibrar": [int(x) for x in result.calibration],
        },
        "metodo": {
            "nombre": "Razón de conteos MODIS/VIIRS por mes del año",
            "unidad": "detecciones equivalentes MODIS",
            "regla": "solo MODIS: M · solo VIIRS: k·V · ambos: (M + k·V) / 2",
            "factores": [round(x, 5) for x in result.factors],
            "factorGlobal": round(result.factor_global, 5),
            "intervalo95": [[round(a, 5), round(b, 5)] for a, b in result.factor_ci],
            "ambitoDelFactor": result.factor_scope,
            "diagnostico": result.diagnostics,
            "semilla": cfg.seed,
        },
        "filtros": {
            "tipos": list(cfg.types),
            "confianzaMinimaModis": cfg.modis_min_confidence,
            "descartaViirsBaja": cfg.viirs_drop_low,
            "mascaraEstaticaNrt": {
                "minimo": cfg.static_mask_min,
                "grados": cfg.static_mask_deg,
            },
        },
        "registros": {
            "leidos": read_count,
            "descartados": log.total(),
            "usados": df.height,
            "detalle": log.rows,
        },
        "totalesMensuales": result.totals,
        "recientes": {"fichero": RECENT, "desde": recent["desde"], "hasta": recent["hasta"]},
        "celdas": CELLS,
        "anios": years,
        "ficheros": files,
        "config": asdict(cfg),
    }
    payload = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    _write(out, MANIFEST, payload)
    return manifest
