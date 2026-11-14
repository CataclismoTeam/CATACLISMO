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
