"""Agrupación de detecciones en incendios, contorno y comunidad autónoma."""

import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from build_hotspots.incidents import IncidentConfig, Regions, build_incidents


def region_files(tmp_path: Path) -> Regions:
    """Dos 'comunidades' contiguas: oeste (lon < -4) y este."""

    def fc(names: list[str]) -> dict:
        boxes = [[-6, 36, -4, 38], [-4, 36, -2, 38]]
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": n},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[w, s], [e, s], [e, n_], [w, n_], [w, s]]],
                    },
                }
                for n, (w, s, e, n_) in zip(names, boxes, strict=True)
            ],
        }

    (tmp_path / "c.geojson").write_text(json.dumps(fc(["Andalucia", "Murcia"])))
    (tmp_path / "p.geojson").write_text(json.dumps(fc(["Málaga", "Murcia"])))
    return Regions(tmp_path / "c.geojson", tmp_path / "p.geojson")


def detections(rows: list[tuple[float, float, date, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "lon": [r[0] for r in rows],
            "lat": [r[1] for r in rows],
            "date": [r[2] for r in rows],
            "minute": [800] * len(rows),
            "sensor": ["VIIRS"] * len(rows),
            "frp": [r[3] for r in rows],
        }
    )


D0 = date(2026, 8, 1)


def test_groups_nearby_detections_and_drops_isolated_ones(tmp_path: Path) -> None:
    fire_a = [(-5.0 + i * 0.003, 37.0, D0 + timedelta(days=i // 4), 10.0 + i) for i in range(8)]
    fire_b = [(-3.0, 37.2 + i * 0.003, D0, 50.0) for i in range(4)]
    lone = [(-5.5, 36.5, D0, 5.0), (-5.5, 36.5005, D0, 5.0)]  # solo 2: no es incendio
    result = build_incidents(detections(fire_a + fire_b + lone), region_files(tmp_path), since=D0)
    incs = result["incendios"]
    assert [i["detecciones"] for i in incs] == [4, 8]  # ordenados por FRP total
    assert [i["comunidad"] for i in incs] == ["Región de Murcia", "Andalucía"]
    assert incs[1]["provincia"] == "Málaga"
    assert result["comunidades"] == ["Andalucía", "Región de Murcia"]
    assert [i["id"] for i in incs] == ["INC-001", "INC-002"]


def test_detections_far_apart_in_time_are_different_fires(tmp_path: Path) -> None:
    rows = [(-5.0, 37.0, D0, 10.0)] * 3 + [(-5.0, 37.0, D0 + timedelta(days=20), 10.0)] * 3
    result = build_incidents(detections(rows), region_files(tmp_path), since=D0)
    assert len(result["incendios"]) == 2
    # Solo el último sigue activo (sin detecciones en los 3 últimos días)
    assert sorted(i["activo"] for i in result["incendios"]) == [False, True]


def test_outline_covers_every_detection_and_is_smooth(tmp_path: Path) -> None:
    rows = [(-5.0 + i * 0.002, 37.0 + (i % 2) * 0.002, D0, 10.0) for i in range(10)]
    inc = build_incidents(detections(rows), region_files(tmp_path), since=D0, cfg=IncidentConfig())[
        "incendios"
    ][0]
    west, south, east, north = inc["bbox"]
    assert west < -5.0 and east > -5.0 + 9 * 0.002
    assert south < 37.0 and north > 37.002
    assert inc["contorno"]["type"] in {"Polygon", "MultiPolygon"}
    assert 0.5 < inc["areaKm2"] < 3
