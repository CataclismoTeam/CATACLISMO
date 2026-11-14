"""Vías de escape de las simulaciones con el algoritmo del equipo (backend/search/main.py).

Para cada simulación se monta una rejilla de 100 m alrededor del foco con datos reales:
carreteras y pistas de OpenStreetMap (Overpass), mar fuera de las comunidades autónomas y
núcleos de población. El algoritmo del equipo propaga el fuego con el viento y busca, con A*
espacio-temporal, la ruta más segura desde cada núcleo amenazado hasta un refugio.

Uso: `build-escape-routes --scenarios frontend/src/map/scenarios.json --out frontend/public/data`
"""

import argparse
import importlib.util
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from shapely import STRtree, points
from shapely.geometry import shape

from .export import write_json

ROOT = Path(__file__).resolve().parents[3]
TEAM_MODULE = ROOT / "backend" / "search" / "main.py"
OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
# Sin datos personales: identificación genérica del cliente
USER_AGENT = "cataclismo-preproceso/1.0 (NASA Space Apps 2026)"

CELL_M = 100.0
HALF_DEG = 0.07  # ~15 km de lado
# Calibración: con matorral y viento, el frente del algoritmo avanza ~0,4 km por turno; con un
# frente realista de ~2 km/h, un turno equivale a ~12 minutos
MIN_PER_TURN = 12.0
# Evacuación en vehículo a ~20 km/h: 4 km en 12 min → 40 celdas de 100 m por turno
VEHICLE_CELLS_PER_TURN = 40.0
ESCAPE_FILE = "escape-routes-v1.json"

ROAD_CHAR = {
    "motorway": "=",
    "trunk": "=",
    "primary": "=",
    "secondary": "=",
    "tertiary": "R",
    "unclassified": "R",
    "residential": "R",
    "track": "-",
}


def load_team_module():
    spec = importlib.util.spec_from_file_location("cataclismo_escape", TEAM_MODULE)
    if not spec or not spec.loader:
        raise ImportError(f"No se encuentra el algoritmo del equipo en {TEAM_MODULE}")
    module = importlib.util.module_from_spec(spec)
    # Los dataclass del módulo necesitan encontrarlo en sys.modules al cargarse
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def overpass(bbox: tuple[float, float, float, float], cache: Path) -> dict:
    """Carreteras y núcleos de población del área (con caché local en data/raw/osm/)."""
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    s, w, n, e = bbox[1], bbox[0], bbox[3], bbox[2]
    roads = "|".join(ROAD_CHAR)
    query = f"""[out:json][timeout:90];
(
  way["highway"~"^({roads})$"]({s},{w},{n},{e});
  node["place"~"^(city|town|village|hamlet|suburb)$"]({s},{w},{n},{e});
);
out geom;"""
    data = urllib.parse.urlencode({"data": query}).encode()
    # Servidores públicos alternativos: si uno está saturado (502/504) se prueba el siguiente
    errors = []
    for attempt, url in enumerate(OVERPASS * 2):
        request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 (URL fija https)
                result = json.loads(response.read())
            break
        except OSError as error:
            errors.append(f"{url}: {error}")
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError("Overpass no responde:\n" + "\n".join(errors))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result), encoding="utf-8")
    return result


class Land:
    """Tierra firme según los límites de las comunidades autónomas (lo demás es mar)."""

    def __init__(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self.geoms = [shape(f["geometry"]) for f in data["features"]]
        self.tree = STRtree(self.geoms)

    def is_land(self, lon: float, lat: float) -> bool:
        return bool(len(self.tree.query(points(lon, lat), predicate="intersects")))


def _line_cells(geo, coords: list[tuple[float, float]], rows: int, cols: int):
    """Celdas que atraviesa una polilínea (muestreo cada media celda)."""
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:], strict=False):
        r1, c1 = geo.latlon_a_grid(lat1, lon1)
        r2, c2 = geo.latlon_a_grid(lat2, lon2)
        steps = max(abs(r2 - r1), abs(c2 - c1)) * 2 + 1
        for k in range(steps + 1):
            r = round(r1 + (r2 - r1) * k / steps)
            c = round(c1 + (c2 - c1) * k / steps)
            if 0 <= r < rows and 0 <= c < cols:
                yield r, c


def _km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    dx = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, (lat2 - lat1) * 111.32)


def routes_for(scenario: dict, team, land: Land, cache_dir: Path) -> dict:
    lon0, lat0 = scenario["ignition"]
    half_lon = HALF_DEG / math.cos(math.radians(lat0))
    bbox = (lon0 - half_lon, lat0 - HALF_DEG, lon0 + half_lon, lat0 + HALF_DEG)
    osm = overpass(bbox, cache_dir / f"{scenario['id']}.json")

    geo = team.GeoReferencia(lat_origen=bbox[3], lon_origen=bbox[0], resolucion_metros=CELL_M)
    rows, cols = geo.latlon_a_grid(bbox[1], bbox[2])
    rows, cols = rows + 1, cols + 1

    # Base: matorral/monte; mar donde no hay tierra (se muestrea cada 5 celdas por rapidez)
    grid = [["V"] * cols for _ in range(rows)]
    for r in range(0, rows, 5):
        for c in range(0, cols, 5):
            lat, lon = geo.grid_a_latlon(r + 2, c + 2)
            if not land.is_land(lon, lat):
                for rr in range(r, min(rows, r + 5)):
                    for cc in range(c, min(cols, c + 5)):
                        grid[rr][cc] = "W"

    places = []
    for el in osm.get("elements", []):
        if el["type"] == "way" and "geometry" in el:
            char = ROAD_CHAR.get(el.get("tags", {}).get("highway", ""))
            if not char:
                continue
            coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
            for r, c in _line_cells(geo, coords, rows, cols):
                current = grid[r][c]
                # La vía más rápida manda (= sobre R sobre -)
                if current not in "=" and not (current == "R" and char == "-"):
                    grid[r][c] = char
        elif el["type"] == "node" and "name" in el.get("tags", {}):
            places.append((el["tags"]["name"], el["lon"], el["lat"], el["tags"]["place"]))

    focus = geo.latlon_a_grid(lat0, lon0)
    grid[focus[0]][focus[1]] = "F"
    towards = math.radians((scenario["windFrom"] + 180) % 360)
    strength = min(1.5, scenario["windKmh"] / 20)
    wind = (-math.cos(towards) * strength, math.sin(towards) * strength)

    fire = team.calcular_tiempos_fuego(grid, [focus], viento=wind)

    def on_road(lon: float, lat: float) -> tuple[int, int] | None:
        """Celda de vía más cercana a un núcleo (los vehículos salen por carretera)."""
        r0, c0 = geo.latlon_a_grid(lat, lon)
        for radius in range(0, 8):
            for r in range(r0 - radius, r0 + radius + 1):
                for c in range(c0 - radius, c0 + radius + 1):
                    if 0 <= r < rows and 0 <= c < cols and grid[r][c] in "=R-":
                        return r, c
        return None

    # Amenazados: núcleos a los que el fuego llega en ≤ 8 h (si no hay, los dos primeros que
    # alcanza). Refugios: núcleos a ≥ 4 km a los que el fuego tardaría ≥ 2,5 veces más.
    reachable = []
    for name, lon, lat, kind in places:
        cell = on_road(lon, lat)
        if cell and _km(lon0, lat0, lon, lat) >= 1.5:
            reachable.append((fire[cell[0]][cell[1]], name, cell, kind, _km(lon0, lat0, lon, lat)))
    reachable.sort()
    threatened = [(t, n, c) for t, n, c, _, _ in reachable if t * MIN_PER_TURN <= 480]
    if not threatened:
        threatened = [(t, n, c) for t, n, c, _, _ in reachable[:2]]
    first = threatened[0][0] if threatened else 0
    taken = {n for _, n, _ in threatened}
    refuges = [
        (n, c)
        for t, n, c, kind, d in reachable
        if n not in taken and d >= 4 and kind != "suburb" and t >= 2.5 * first
    ]

    routes = []
    exits = [cell for _, cell in refuges]
    if exits:
        for t_fire, name, start in threatened[:3]:
            path, _ = team.encontrar_via_escape(
                grid,
                inicio=start,
                salida=exits,
                focos_incendio=[focus],
                permitir_diagonales=True,
                margen_seguridad=2.0,
                peso_riesgo=0.8,
                tiempo_fuego_previo=fire,
                viento=wind,
                velocidad_persona=VEHICLE_CELLS_PER_TURN,
            )
            if not path:
                continue
            metrics = team.calcular_metricas_evacuacion(
                path, fire, resolucion_metros=CELL_M, velocidad_persona=VEHICLE_CELLS_PER_TURN
            )
            line = team.ruta_a_geojson(path, None, geo_ref=geo)["features"][0]["geometry"]
            refuge = next(n for n, cell in refuges if cell == tuple(path[-1]))
            margin = metrics.get("margen_minimo_fuego")
            routes.append(
                {
                    "nombre": f"{name} → {refuge}",
                    "desde": name,
                    "refugio": refuge,
                    "coords": [[round(x, 5), round(y, 5)] for x, y in line["coordinates"][::2]]
                    + [[round(c, 5) for c in line["coordinates"][-1]]],
                    "distanciaKm": round(metrics["distancia_metros"] / 1000, 1),
                    "tiempoMin": round(metrics["tiempo_estimado"] * MIN_PER_TURN),
                    "margenMin": round(margin * MIN_PER_TURN) if margin is not None else None,
                    "llegadaFuegoMin": round(t_fire * MIN_PER_TURN),
                }
            )
    return {"rutas": routes, "nucleos": len(places)}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="build-escape-routes", description=__doc__)
    p.add_argument("--scenarios", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--regions", type=Path, default=ROOT / "data/raw/limites")
    p.add_argument("--cache", type=Path, default=ROOT / "data/raw/osm")
    args = p.parse_args(argv)

    team = load_team_module()
    land = Land(args.regions / "spain-communities.geojson")
    scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))
    result = {
        "metodo": (
            "Algoritmo de vías de escape del equipo (backend/search/main.py): propagación con "
            "viento y A* espacio-temporal sobre rejilla de 100 m con carreteras de OpenStreetMap"
        ),
        "unidades": {"turnoMin": MIN_PER_TURN, "celdaM": CELL_M},
        "atribucion": "Vías y núcleos © colaboradores de OpenStreetMap (ODbL)",
        "escenarios": {},
    }
    for s in scenarios:
        try:
            info = routes_for(s, team, land, args.cache)
        except RuntimeError as error:
            # Overpass saturado: esa simulación se queda sin rutas, las demás siguen
            print(f"{s['id']:12s} sin rutas: {error}".splitlines()[0], flush=True)
            result["escenarios"][s["id"]] = {"rutas": [], "nucleos": 0}
            continue
        result["escenarios"][s["id"]] = info
        print(f"{s['id']:12s} {len(info['rutas'])} rutas · {info['nucleos']} núcleos", flush=True)
        for r in info["rutas"]:
            print(
                f"   {r['nombre']}: {r['distanciaKm']} km, {r['tiempoMin']} min, "
                f"margen {r['margenMin']} min",
                flush=True,
            )
    write_json(args.out, ESCAPE_FILE, result)


if __name__ == "__main__":
    main()
