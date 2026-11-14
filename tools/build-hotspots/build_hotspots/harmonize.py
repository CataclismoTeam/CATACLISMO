"""Agregado mensual por celda y calibración de VIIRS respecto a MODIS.

Método (razón de conteos por mes del año, estimador de razón):

1. Se cuentan las detecciones por celda, mes y sensor.
2. Con los meses completos en que ambos sensores funcionan y el dato es estándar (no NRT),
   se calcula para cada mes del año k = Σ MODIS / Σ VIIRS sobre toda el área. El factor es
   estacional porque VIIRS (375 m) ve muchos fuegos pequeños que MODIS (1 km) no detecta,
   y su proporción cambia entre el invierno (quemas agrícolas) y el verano (grandes incendios).
3. El conteo armonizado se expresa en "detecciones equivalentes MODIS":
     solo MODIS          → M
     solo VIIRS          → k · V
     ambos funcionando   → (M + k · V) / 2
   Así la serie no salta cuando un sensor entra o sale, y con los dos activos se promedian
   dos estimaciones de la misma magnitud.

Se usa una razón sobre el área completa y no por celda porque a 5 km la mayoría de las
celdas tiene muy pocas detecciones y una razón local sería ruido.
"""

import calendar
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from .config import Config, Grid

SENSORS = ("MODIS", "VIIRS")


@dataclass
class Harmonized:
    cells: pl.DataFrame  # gid, mi, m, v, h, frp_m, frp_v
    start_year: int
    n_months: int
    factors: list[float]
    factor_global: float
    factor_ci: list[list[float]]
    factor_scope: list[str]
    days_in_month: list[int]
    days_covered: dict[str, list[int]]
    provisional: list[int]
    calibration: list[bool]
    totals: dict[str, list[float]]
    sensor_ranges: dict[str, dict[str, str]]
    diagnostics: dict[str, object]


def assign_cells(df: pl.DataFrame, grid: Grid, start_year: int) -> pl.DataFrame:
    row = ((pl.col("lat") - grid.south) / grid.cell_deg).floor().clip(0, grid.nrows - 1)
    col = ((pl.col("lon") - grid.west) / grid.cell_deg).floor().clip(0, grid.ncols - 1)
    return df.with_columns(
        (row.cast(pl.Int64) * grid.ncols + col.cast(pl.Int64)).cast(pl.UInt32).alias("gid"),
        ((pl.col("date").dt.year() - start_year) * 12 + pl.col("date").dt.month() - 1)
        .cast(pl.Int32)
        .alias("mi"),
    )


def _coverage(first: date, last: date, start_year: int, n_months: int) -> list[int]:
    """Días de cada mes dentro del periodo observado por un sensor."""
    days = []
    for mi in range(n_months):
        year, month = start_year + mi // 12, mi % 12 + 1
        month_first = date(year, month, 1)
        month_last = date(year, month, calendar.monthrange(year, month)[1])
        lo, hi = max(first, month_first), min(last, month_last)
        days.append(max(0, (hi - lo).days + 1))
    return days


def calibration_factors(
    m_tot: np.ndarray, v_tot: np.ndarray, calibration: np.ndarray, cfg: Config
) -> tuple[list[float], float, list[list[float]], list[str]]:
    """Factor k por mes del año, factor global e intervalo bootstrap (remuestreo de años)."""
    n_years = len(m_tot) // 12
    m = np.where(calibration, m_tot, 0.0).reshape(n_years, 12)
    v = np.where(calibration, v_tot, 0.0).reshape(n_years, 12)
    if v.sum() <= 0 or m.sum() <= 0:
        # Sin solapamiento no hay nada que calibrar: los conteos se dejan tal cual
        return [1.0] * 12, 1.0, [[1.0, 1.0]] * 12, ["sin solapamiento"] * 12
    k_global = float(m.sum() / v.sum())
    own = (v.sum(axis=0) >= cfg.min_calibration_count) & (m.sum(axis=0) > 0)
    k = np.where(own, m.sum(axis=0) / np.maximum(v.sum(axis=0), 1e-9), k_global)

    rng = np.random.default_rng(cfg.seed)
    picks = rng.integers(0, n_years, size=(cfg.bootstrap_samples, n_years))
    ms, vs = m[picks].sum(axis=1), v[picks].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        kb = np.where(vs > 0, ms / vs, np.nan)
    lo, hi = np.nanpercentile(kb, [2.5, 97.5], axis=0)
    ci = [[float(lo[c]), float(hi[c])] if own[c] else [k_global, k_global] for c in range(12)]
    scope = ["mes del año" if own[c] else "global" for c in range(12)]
    return [float(x) for x in k], k_global, ci, scope


def harmonize(df: pl.DataFrame, cfg: Config) -> Harmonized:
    if df.is_empty():
        raise ValueError("No queda ninguna detección tras los filtros")
    first, last = df["date"].min(), df["date"].max()
    start_year = first.year
    n_months = (last.year - start_year + 1) * 12
    df = assign_cells(df, cfg.grid, start_year)

    agg = df.group_by("gid", "mi", "sensor").agg(
        pl.len().alias("n"), pl.col("frp").sum().alias("frp")
    )

    def side(sensor: str, count: str, frp: str) -> pl.DataFrame:
        return agg.filter(pl.col("sensor") == sensor).select(
            "gid", "mi", pl.col("n").alias(count), pl.col("frp").alias(frp)
        )

    cells = (
        side("MODIS", "m", "frp_m")
        .join(side("VIIRS", "v", "frp_v"), on=["gid", "mi"], how="full", coalesce=True)
        .fill_null(0)
        .sort("mi", "gid")
    )

    ranges = {
        s: (sub["date"].min(), sub["date"].max())
        for s in SENSORS
        if not (sub := df.filter(pl.col("sensor") == s)).is_empty()
    }
    covered = {
        s: _coverage(*ranges[s], start_year, n_months) if s in ranges else [0] * n_months
        for s in SENSORS
    }
    dim = [calendar.monthrange(start_year + mi // 12, mi % 12 + 1)[1] for mi in range(n_months)]

    # Meses provisionales: bit 1 = MODIS con NRT, bit 2 = VIIRS con NRT
    provisional = [0] * n_months
    nrt = df.filter(pl.col("quality") == "nrt").select("mi", "sensor").unique()
    for mi, sensor in nrt.iter_rows():
        provisional[mi] |= 1 if sensor == "MODIS" else 2

    m_tot, v_tot = np.zeros(n_months), np.zeros(n_months)
    monthly = cells.group_by("mi").agg(pl.col("m").sum(), pl.col("v").sum())
    for mi, m, v in monthly.iter_rows():
        m_tot[mi], v_tot[mi] = m, v

    on_m, on_v = np.array(covered["MODIS"]) > 0, np.array(covered["VIIRS"]) > 0
    full = (np.array(covered["MODIS"]) == dim) & (np.array(covered["VIIRS"]) == dim)
    calibration = full & (np.array(provisional) == 0)
    factors, k_global, ci, scope = calibration_factors(m_tot, v_tot, calibration, cfg)

    k = np.array(factors)
    mi_arr = cells["mi"].to_numpy()
    m_arr = cells["m"].to_numpy().astype(np.float64)
    kv = k[mi_arr % 12] * cells["v"].to_numpy()
    both, only_m = on_m[mi_arr] & on_v[mi_arr], on_m[mi_arr] & ~on_v[mi_arr]
    h = np.where(both, (m_arr + kv) / 2, np.where(only_m, m_arr, kv))
    cells = cells.with_columns(pl.Series("h", h, dtype=pl.Float64))

    h_tot = np.zeros(n_months)
    np.add.at(h_tot, mi_arr, h)

    # Diagnóstico sobre los meses de calibración: ¿cuánto se parecen MODIS y k·VIIRS?
    kv_tot = k[np.arange(n_months) % 12] * v_tot
    cal_m, cal_kv = m_tot[calibration], kv_tot[calibration]
    by_year = {}
    for y in range(n_months // 12):
        sel = calibration & (np.arange(n_months) // 12 == y)
        if v_tot[sel].sum() > 0:
            by_year[str(start_year + y)] = round(float(m_tot[sel].sum() / v_tot[sel].sum()), 4)
    nonzero = cal_m > 0
    diagnostics = {
        "mesesDeCalibracion": int(calibration.sum()),
        "correlacionMensual": round(float(np.corrcoef(cal_m, cal_kv)[0, 1]), 4)
        if calibration.sum() > 2
        else None,
        "errorRelativoMediano": round(
            float(np.median(np.abs(cal_kv[nonzero] - cal_m[nonzero]) / cal_m[nonzero])), 4
        )
        if nonzero.any()
        else None,
        "razonPorAnio": by_year,
    }

    return Harmonized(
        cells=cells,
        start_year=start_year,
        n_months=n_months,
        factors=factors,
        factor_global=k_global,
        factor_ci=ci,
        factor_scope=scope,
        days_in_month=dim,
        days_covered=covered,
        provisional=provisional,
        calibration=[bool(x) for x in calibration],
        totals={
            "modis": [float(x) for x in m_tot],
            "viirs": [float(x) for x in v_tot],
            "armonizado": [round(float(x), 2) for x in h_tot],
        },
        sensor_ranges={
            s: {"desde": lo.isoformat(), "hasta": hi.isoformat()} for s, (lo, hi) in ranges.items()
        },
        diagnostics=diagnostics,
    )
