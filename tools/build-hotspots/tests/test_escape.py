"""Vías de escape con el algoritmo del equipo sobre una red de carreteras sintética (sin red)."""

import json
from pathlib import Path

from build_hotspots.escape import Land, load_team_module, routes_for


def test_route_goes_from_threatened_village_to_upwind_refuge(tmp_path: Path) -> None:
    # Tierra firme alrededor del foco
    land_file = tmp_path / "land.geojson"
    land_file.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Tierra"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[-1, 39], [1, 39], [1, 41], [-1, 41], [-1, 39]]],
                        },
                    }
                ],
            }
        )
    )
    # Viento del oeste: el fuego avanza al este. Carretera oeste-este con un pueblo amenazado
    # al este (2,6 km) y un refugio al oeste (6,8 km, a contraviento)
    osm = {
        "elements": [
            {
                "type": "way",
                "tags": {"highway": "secondary"},
                "geometry": [{"lon": x / 100, "lat": 40.01} for x in range(-9, 6)],
            },
            {
                "type": "node",
                "lon": 0.03,
                "lat": 40.01,
                "tags": {"name": "Amenazado", "place": "village"},
            },
            {
                "type": "node",
                "lon": -0.08,
                "lat": 40.01,
                "tags": {"name": "Refugio", "place": "town"},
            },
        ]
    }
    cache = tmp_path / "osm"
    cache.mkdir()
    (cache / "prueba.json").write_text(json.dumps(osm))
    scenario = {"id": "prueba", "ignition": [0.0, 40.0], "windFrom": 270, "windKmh": 25}

    result = routes_for(scenario, load_team_module(), Land(land_file), cache)

    assert result["nucleos"] == 2
    [route] = result["rutas"]
    assert route["desde"] == "Amenazado"
    assert route["refugio"] == "Refugio"
    assert route["coords"][0][0] > route["coords"][-1][0]  # de este a oeste
    assert 8 < route["distanciaKm"] < 16
    assert route["tiempoMin"] > 0


def test_snap_to_roads_replaces_grid_staircase_with_real_road() -> None:
    from build_hotspots.escape import snap_to_roads

    # Carretera recta oeste-este y una ruta de rejilla en escalera alrededor de ella
    road = [{"lon": x / 1000, "lat": 40.0} for x in range(0, 101, 10)]
    osm = {"elements": [{"type": "way", "tags": {"highway": "secondary"}, "geometry": road}]}
    wobble = [0.0004 if (x // 10) % 2 else -0.0004 for x in range(0, 101, 10)]
    staircase = [(x / 1000, 40.0 + w) for x, w in zip(range(0, 101, 10), wobble, strict=True)]

    snapped = snap_to_roads(staircase, osm)

    assert all(abs(lat - 40.0) < 1e-6 for _, lat in snapped)
    assert snapped[0][0] == 0 and snapped[-1][0] == 0.1
    # La recta se simplifica a sus extremos: sin puntos de sobra
    assert len(snapped) == 2


def test_snap_to_roads_keeps_original_when_no_connected_road() -> None:
    from build_hotspots.escape import snap_to_roads

    original = [(0.0, 40.0), (0.01, 40.0)]
    assert snap_to_roads(original, {"elements": []}) == original
