"""Pruebas del preproceso con detecciones sintéticas (no necesitan los datos de FIRMS)."""

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from build_hotspots.cli import main
from build_hotspots.config import Config, Grid
from build_hotspots.export import CELLS, MANIFEST, RECENT
from build_hotspots.harmonize import harmonize
from build_hotspots.ingest import DiscardLog, apply_filters, read_records

GRID = Grid(-10.0, 35.0, 5.0, 44.0, cell_deg=0.05)
CFG = Config(grid=GRID, min_calibration_count=1, bootstrap_samples=50)


def rec(sensor: str, day: date, lat: float, lon: float, **over: object) -> dict[str, object]:
    modis = sensor == "MODIS"
    base = {
        "latitude": lat,
        "longitude": lon,
        "acq_date": day.isoformat(),
        "acq_time": "1342",
        "version": "6.03" if modis else "2",
        "instrument": "MODIS" if modis else "SNPP",
        "satellite": "Aqua" if modis else "SNPP",
        "confidence": "76" if modis else "n",
        "type": "0",
        "daynight": "D",
        "frp": 10.0,
        "bright_t31": 290,
        "brightness": 320,
        "scan": 1,
        "track": 1,
    }
    return {**base, **over}


def dataset() -> list[dict[str, object]]:
    """Dos años completos: cada día 1 detección MODIS y 3 VIIRS en la misma celda."""
    rows = []
    day = date(2020, 1, 1)
    while day <= date(2021, 12, 31):
        rows.append(rec("MODIS", day, 40.012, -3.512))
        for i in range(3):
            rows.append(rec("VIIRS", day, 40.012 + i * 0.001, -3.512))
        day += timedelta(days=1)
    return rows


def write(tmp_path: Path, rows: list[dict[str, object]], name: str = "fire.json") -> Path:
    src = tmp_path / "raw"
    src.mkdir(exist_ok=True)
    (src / name).write_text(json.dumps(rows), encoding="utf-8")
    return src


def load(tmp_path: Path, rows: list[dict[str, object]], cfg: Config = CFG):
    log = DiscardLog()
    src = write(tmp_path, rows)
    raw = read_records(sorted(src.glob("*.json")), log)
    return apply_filters(raw, cfg, log), log


def test_factor_recovers_known_ratio(tmp_path: Path) -> None:
    df, _ = load(tmp_path, dataset())
    result = harmonize(df, CFG)
    assert result.factors == pytest.approx([1 / 3] * 12)
    # Con ambos sensores activos, (M + k·V) / 2 = M cuando VIIRS ve exactamente 3 veces más
    assert result.cells["h"].to_list() == pytest.approx(result.cells["m"].to_list())


def test_raw_counts_are_conserved(tmp_path: Path) -> None:
    df, log = load(tmp_path, dataset())
    result = harmonize(df, CFG)
    assert result.cells["m"].sum() + result.cells["v"].sum() == df.height
    assert sum(result.totals["modis"]) + sum(result.totals["viirs"]) == df.height
    assert log.total() == 0


def test_harmonized_equals_raw_without_calibration(tmp_path: Path) -> None:
    """Con un solo sensor no hay nada que calibrar: armonizado = bruto."""
    rows = [r for r in dataset() if r["instrument"] == "MODIS"]
    df, _ = load(tmp_path, rows)
    result = harmonize(df, CFG)
    assert result.factors == [1.0] * 12
    assert result.cells["h"].sum() == pytest.approx(df.height)


def test_filters_are_logged(tmp_path: Path) -> None:
    day = date(2020, 6, 1)
    rows = [
        rec("MODIS", day, 40.0, -3.0),
        rec("MODIS", day, 40.0, -3.0),  # duplicada exacta
        rec("MODIS", day, 40.1, -3.0, confidence="12"),  # confianza baja
        rec("VIIRS", day, 40.2, -3.0, confidence="l"),  # confianza baja
        rec("VIIRS", day, 40.3, -3.0, type="2"),  # fuente estática
        rec("VIIRS", day, 60.0, -3.0),  # fuera del área
        rec("VIIRS", day, 40.4, -3.0),
        {"latitude": "x"},  # no válido
    ]
    df, log = load(tmp_path, rows)
    assert df.height == 2
    assert log.total() == 6
    steps = {r["paso"].split(" ")[0] for r in log.rows}
    assert steps == {"registro", "fuera", "duplicada", "tipo", "confianza"}


def test_nrt_splice_has_no_overlap_or_gap(tmp_path: Path) -> None:
    std = [rec("VIIRS", date(2020, 7, d), 40.0, -3.0, acq_time=f"{d:04d}") for d in (1, 2, 3)]
    nrt = [
        rec("VIIRS", date(2020, 7, d), 40.0, -3.0, acq_time=f"{d:04d}", version="2.0NRT")
        for d in (3, 4, 5)
    ]
    for r in nrt:
        del r["type"]
    df, log = load(tmp_path, std + nrt)
    assert sorted(df["date"].dt.day().to_list()) == [1, 2, 3, 4, 5]
    assert df.filter(df["quality"] == "nrt").height == 2
    assert log.total() == 1


def test_nrt_static_sources_are_masked(tmp_path: Path) -> None:
    std = [
        rec("VIIRS", date(2020, 7, d), 41.5, 2.1, type="2", acq_time=f"{d:04d}") for d in (1, 2, 3)
    ]
    nrt = rec("VIIRS", date(2020, 8, 1), 41.5, 2.1, version="2.0NRT")
    del nrt["type"]
    fire = rec("VIIRS", date(2020, 8, 1), 40.0, -3.0, version="2.0NRT")
    del fire["type"]
    df, _ = load(tmp_path, std + [nrt, fire])
    assert df.height == 1
    assert df["lat"].to_list() == [40.0]


def test_cells_stay_inside_bbox(tmp_path: Path) -> None:
    rows = dataset() + [
        rec("MODIS", date(2020, 3, 1), 35.0, -10.0),  # esquina suroeste (incluida)
        rec("MODIS", date(2020, 3, 1), 43.9999, 4.9999),  # junto a la esquina noreste
    ]
    df, _ = load(tmp_path, rows)
    gids = harmonize(df, CFG).cells["gid"].to_numpy()
    assert gids.min() == 0
    assert gids.max() == GRID.nrows * GRID.ncols - 1


def test_partial_and_provisional_months_do_not_calibrate(tmp_path: Path) -> None:
    rows = dataset()
    extra = [rec("VIIRS", date(2022, 1, d), 40.0, -3.5, version="2.0NRT") for d in range(1, 11)]
    for r in extra:
        del r["type"]
    extra += [rec("MODIS", date(2022, 1, d), 40.0, -3.5) for d in range(1, 11)]
    df, _ = load(tmp_path, rows + extra)
    result = harmonize(df, CFG)
    jan_2022 = 24
    assert result.provisional[jan_2022] == 2
    assert result.days_covered["MODIS"][jan_2022] == 10
    assert not result.calibration[jan_2022]
    assert all(result.calibration[:24])


def test_cli_writes_readable_outputs(tmp_path: Path) -> None:
    src = write(tmp_path, dataset())
    out = tmp_path / "out"
    main(["--in", str(src), "--out", str(out), "--bbox", "-10", "35", "5", "44"])
    manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    cells = np.frombuffer((out / CELLS).read_bytes(), dtype="<u4")
    assert manifest["rejilla"]["celdasConDatos"] == len(cells) == 1

    total_m = total_v = 0
    total_h = 0.0
    for year in manifest["anios"]:
        buf = (out / year["fichero"]).read_bytes()
        n = year["entradas"]
        assert len(buf) == n * 19
        h = np.frombuffer(buf, dtype="<f4", count=n)
        cell = np.frombuffer(buf, dtype="<u2", count=n, offset=12 * n)
        m = np.frombuffer(buf, dtype="<u2", count=n, offset=14 * n)
        v = np.frombuffer(buf, dtype="<u2", count=n, offset=16 * n)
        month = np.frombuffer(buf, dtype="u1", count=n, offset=18 * n)
        assert set(month) == set(range(12))
        assert set(cell) == {0}
        total_m, total_v, total_h = (
            total_m + int(m.sum()),
            total_v + int(v.sum()),
            total_h + h.sum(),
        )
    assert total_m == 731
    assert total_v == 2193
    assert total_h == pytest.approx(731)
    assert manifest["registros"]["usados"] == 731 + 2193

    recent = json.loads((out / RECENT).read_text(encoding="utf-8"))
    assert recent["hasta"] == "2021-12-31"
    assert len(recent["lat"]) == len(recent["t"]) == 90 * 4


def test_same_seed_gives_same_intervals(tmp_path: Path) -> None:
    df, _ = load(tmp_path, dataset())
    a = harmonize(df, CFG)
    b = harmonize(df, CFG)
    c = harmonize(df, replace(CFG, seed=1))
    assert a.factor_ci == b.factor_ci
    assert len(c.factor_ci) == 12
