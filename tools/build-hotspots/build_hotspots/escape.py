"""Vías de escape de las simulaciones con el algoritmo del equipo.

Algoritmo: backend/app/lucia/prototype_astar.py.

Para cada simulación se monta una rejilla de 100 m alrededor del foco con datos reales:
carreteras y pistas de OpenStreetMap (Overpass), mar fuera de las comunidades autónomas y
núcleos de población. El algoritmo del equipo propaga el fuego con el viento y busca, con A*
espacio-temporal, la ruta más segura desde cada núcleo amenazado hasta un refugio.

Uso: `build-escape-routes --scenarios frontend/src/map/scenarios.json --out frontend/public/data`
"""

import argparse
import heapq
import importlib.util
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from shapely import STRtree, points
from shapely.geometry import LineString, shape

from .export import write_json

ROOT = Path(__file__).resolve().parents[3]
TEAM_MODULE = ROOT / "backend" / "app" / "lucia" / "prototype_astar.py"
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
VEHICLE_KMH = VEHICLE_CELLS_PER_TURN * CELL_M / 1000 * 60 / MIN_PER_TURN  # = 20 km/h
ESCAPE_FILE = "escape-routes-v1.json"
# La ruta de la rejilla (100 m) se pega a la carretera real dentro de este pasillo; si no hay
# camino conectado se amplía, y como último recurso se conserva la de la rejilla.
SNAP_CORRIDORS_M = (150.0, 300.0, 600.0, 1200.0, 2500.0)
# Tolerancia al simplificar la línea final (a escala de calle no se nota y pesa mucho menos)
SIMPLIFY_M = 4.0
# En OSM dos vías pueden cruzarse sin compartir nodo (pasos, pistas que desembocan en la carretera):
# la rejilla de 100 m sí las conecta (hasta ~1,5 celdas): se enlazan los tramos a menos de esto,
# con un coste mayor que el de una intersección real.
BRIDGE_M = 150.0
BRIDGE_PENALTY = 2.0
# Último recurso: un pueblo o una pista pueden quedar aislados en OSM (huecos de datos). Se admite
# un único puente, el más corto, por cada par de zonas desconectadas, hasta esta distancia.
GAP_M = 600.0
# Pegar la ruta a la carretera no puede alargarla más de esto respecto a la del algoritmo
MAX_SNAP_DETOUR = 1.6

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


def _metric(lat0: float):
    """Proyección plana local (metros) alrededor de una latitud: suficiente a ~15 km."""
    kx = 111_320.0 * math.cos(math.radians(lat0))
    return (lambda lon, lat: (lon * kx, lat * 111_320.0)), kx


def _components(adjacency: dict) -> dict:
    component: dict = {}
    count = 0
    for root in adjacency:
        if root in component:
            continue
        count += 1
        component[root] = count
        stack = [root]
        while stack:
            for other, _ in adjacency[stack.pop()]:
                if other not in component:
                    component[other] = count
                    stack.append(other)
    return component


def _bridge_gaps(adjacency: dict, metric: dict) -> None:
    """Último recurso: un puente (el más corto, hasta GAP_M) por cada par de zonas aisladas."""
    component = _components(adjacency)
    if len(set(component.values())) == 1:
        return
    nodes = list(metric)
    best: dict[tuple[int, int], tuple[float, tuple, tuple]] = {}
    buckets: dict[tuple[int, int], list] = {}
    for n in nodes:
        buckets.setdefault((int(metric[n][0] // GAP_M), int(metric[n][1] // GAP_M)), []).append(n)
    for n in nodes:
        x, y = metric[n]
        bx, by = int(x // GAP_M), int(y // GAP_M)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for m in buckets.get((bx + dx, by + dy), ()):
                    if component[m] <= component[n]:
                        continue
                    d = math.hypot(metric[m][0] - x, metric[m][1] - y)
                    pair = (component[n], component[m])
                    if d <= GAP_M and (pair not in best or d < best[pair][0]):
                        best[pair] = (d, n, m)
    for d, a, b in best.values():
        adjacency[a].append((b, d * BRIDGE_PENALTY))
        adjacency[b].append((a, d * BRIDGE_PENALTY))


def _bridge_components(adjacency: dict, metric: dict) -> None:
    """Une con enlaces penalizados las componentes de la red que quedan a menos de BRIDGE_M."""
    component = _components(adjacency)
    if len(set(component.values())) == 1:
        return
    buckets: dict[tuple[int, int], list] = {}
    for n, (x, y) in metric.items():
        buckets.setdefault((int(x // BRIDGE_M), int(y // BRIDGE_M)), []).append(n)
    # Cada nodo se enlaza con el nodo más cercano de cada otra componente (si está a < BRIDGE_M):
    # hay puentes a lo largo de toda la red, no solo en el punto de mayor cercanía global
    for n, (x, y) in metric.items():
        bx, by = int(x // BRIDGE_M), int(y // BRIDGE_M)
        nearest_in: dict[int, tuple[float, tuple]] = {}
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for m in buckets.get((bx + dx, by + dy), ()):
                    if component[m] == component[n]:
                        continue
                    d = math.hypot(metric[m][0] - x, metric[m][1] - y)
                    c = component[m]
                    if d <= BRIDGE_M and (c not in nearest_in or d < nearest_in[c][0]):
                        nearest_in[c] = (d, m)
        for d, m in nearest_in.values():
            adjacency[n].append((m, d * BRIDGE_PENALTY))


def snap_to_roads(
    coords: list[tuple[float, float]], osm: dict, corridors_m: tuple[float, ...] = SNAP_CORRIDORS_M
) -> list[tuple[float, float]]:
    """Pega una ruta de rejilla a la geometría real de las carreteras de OpenStreetMap.

    Busca el camino más corto por la red viaria que parte del punto de la carretera más cercano
    al inicio y llega al más cercano al final, pero solo por vías dentro de un pasillo alrededor
    de la ruta original: así mantiene su coherencia (mismo recorrido, mismo refugio) y deja de
    tener los escalones y diagonales de la rejilla. Si no hay camino conectado devuelve la
    original.
    """
    if len(coords) < 2:
        return coords
    to_m, _ = _metric(coords[0][1])
    guide = LineString([to_m(lon, lat) for lon, lat in coords])
    # Grafo por coordenadas: los nodos compartidos de OSM tienen coordenadas idénticas
    key = lambda lon, lat: (round(lon, 6), round(lat, 6))  # noqa: E731
    adjacency: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = {}
    for el in osm.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        if el.get("tags", {}).get("highway") not in ROAD_CHAR:
            continue
        pts = [key(p["lon"], p["lat"]) for p in el["geometry"]]
        for a, b in zip(pts, pts[1:], strict=False):
            if a == b:
                continue
            ax, ay = to_m(*a)
            bx, by = to_m(*b)
            w = math.hypot(bx - ax, by - ay)
            adjacency.setdefault(a, []).append((b, w))
            adjacency.setdefault(b, []).append((a, w))
    if not adjacency:
        return coords

    nodes = list(adjacency)
    metric = {n: to_m(*n) for n in nodes}
    _bridge_components(adjacency, metric)
    distance_to_guide = {n: guide.distance(points(*metric[n])) for n in nodes}

    def nearest(point: tuple[float, float]) -> tuple[float, float]:
        px, py = to_m(*point)
        return min(nodes, key=lambda n: (metric[n][0] - px) ** 2 + (metric[n][1] - py) ** 2)

    start, goal = nearest(coords[0]), nearest(coords[-1])
    for with_gaps in (False, True):
        if with_gaps:
            _bridge_gaps(adjacency, metric)
        result = _shortest(adjacency, metric, distance_to_guide, start, goal, corridors_m)
        if result:
            return result
    return coords


def _shortest(adjacency, metric, distance_to_guide, start, goal, corridors_m):
    nodes = list(adjacency)
    for corridor in corridors_m:
        allowed = {n for n in nodes if distance_to_guide[n] <= corridor} | {start, goal}
        best: dict[tuple[float, float], float] = {start: 0.0}
        parent: dict[tuple[float, float], tuple[float, float]] = {}
        queue = [(0.0, start)]
        while queue:
            cost, node = heapq.heappop(queue)
            if node == goal:
                break
            if cost > best.get(node, math.inf):
                continue
            for other, w in adjacency[node]:
                # Pesa más alejarse de la ruta guía: entre dos caminos, el más fiel a ella
                step = w * (1 + distance_to_guide[other] / 300.0)
                if other in allowed and cost + step < best.get(other, math.inf):
                    best[other] = cost + step
                    parent[other] = node
                    heapq.heappush(queue, (cost + step, other))
        if goal in best:
            path = [goal]
            while path[-1] != start:
                path.append(parent[path[-1]])
            path.reverse()
            line = LineString([metric[n] for n in path]).simplify(SIMPLIFY_M)
            kept = {metric[n]: n for n in path}
            return [kept[(x, y)] for x, y in line.coords if (x, y) in kept]
    return None


def _length_km(line: list) -> float:
    return sum(_km(a[0], a[1], b[0], b[1]) for a, b in zip(line, line[1:], strict=False))


def _road_components(grid: list[list[str]]) -> dict[tuple[int, int], int]:
    """Componente conexa (8 vecinos) de cada celda de vía de la rejilla."""
    rows, cols = len(grid), len(grid[0])
    component: dict[tuple[int, int], int] = {}
    count = 0
    for r0 in range(rows):
        for c0 in range(cols):
            if grid[r0][c0] not in "=R-" or (r0, c0) in component:
                continue
            count += 1
            component[(r0, c0)] = count
            stack = [(r0, c0)]
            while stack:
                r, c = stack.pop()
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        n = (r + dr, c + dc)
                        if (
                            0 <= n[0] < rows
                            and 0 <= n[1] < cols
                            and n not in component
                            and grid[n[0]][n[1]] in "=R-"
                        ):
                            component[n] = count
                            stack.append(n)
    return component


def exits_cells(refuges: list) -> list[tuple[int, int]]:
    return [cell for _, cell in refuges]


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
    safe = [
        (n, c, kind)
        for t, n, c, kind, d in reachable
        if n not in taken and d >= 4 and t >= 2.5 * first
    ]
    # El refugio tiene que poder alcanzarse por carretera desde los amenazados: si no, la búsqueda
    # por vías falla y la ruta sale campo a través. Se prefiere un pueblo; si ninguno conectado
    # cumple, sirve una urbanización; solo sin ninguno conectado se mantiene el criterio original.
    component = _road_components(grid)
    linked = {component[c] for _, _, c in threatened if c in component}
    refuges = (
        [(n, c) for n, c, kind in safe if kind != "suburb" and component.get(c) in linked]
        or [(n, c) for n, c, _ in safe if component.get(c) in linked]
        or [(n, c) for n, c, kind in safe if kind != "suburb"]
    )

    # Evacuación en vehículo: solo por carreteras y pistas. Con la rejilla completa el algoritmo
    # (pensado a pie) atajaba por matorral y la ruta salía del asfalto. Si por un hueco de datos
    # de OSM no hay camino, se usa la rejilla completa como último recurso.
    road_grid = [["#" if ch not in "=R-" else ch for ch in row] for row in grid]
    for r, c in [*[cell for _, _, cell in threatened], *exits_cells(refuges)]:
        road_grid[r][c] = grid[r][c] if grid[r][c] in "=R-" else "R"

    def search(search_grid, start, exits):
        return team.encontrar_via_escape(
            search_grid,
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

    routes = []
    exits = exits_cells(refuges)
    if exits:
        for t_fire, name, start in threatened[:3]:
            path, _ = search(road_grid, start, exits)
            if not path:
                path, _ = search(grid, start, exits)
            if not path:
                continue
            metrics = team.calcular_metricas_evacuacion(
                path, fire, resolucion_metros=CELL_M, velocidad_persona=VEHICLE_CELLS_PER_TURN
            )
            line = team.ruta_a_geojson(path, None, geo_ref=geo)["features"][0]["geometry"]
            raw = [tuple(c) for c in line["coordinates"]]
            snapped = snap_to_roads(raw, osm)
            length_km = _length_km(snapped)
            # Coherencia: si pegarse a la carretera obliga a un rodeo muy distinto del recorrido
            # que eligió el algoritmo, no se acepta (sus tiempos y márgenes ya no valdrían)
            if length_km > MAX_SNAP_DETOUR * _length_km(raw):
                snapped, length_km = raw, _length_km(raw)
            refuge = next(n for n, cell in refuges if cell == tuple(path[-1]))
            margin = metrics.get("margen_minimo_fuego")
            minutes = round(length_km / VEHICLE_KMH * 60)
            # La carretera real es más larga que el camino en diagonal de la rejilla: ese tiempo
            # extra se resta del margen frente al fuego (si queda sin margen, la ruta no vale)
            extra = max(0, minutes - metrics["tiempo_estimado"] * MIN_PER_TURN)
            margin_min = None if margin is None else round(margin * MIN_PER_TURN - extra)
            if margin_min is not None and margin_min <= 0:
                continue
            routes.append(
                {
                    "nombre": f"{name} → {refuge}",
                    "desde": name,
                    "refugio": refuge,
                    "coords": [[round(x, 5), round(y, 5)] for x, y in snapped],
                    # Sobre la carretera real, no sobre la rejilla: distancia y tiempo coherentes
                    "distanciaKm": round(length_km, 1),
                    "tiempoMin": minutes,
                    "margenMin": margin_min,
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
            "Algoritmo de vías de escape del equipo (backend/app/lucia/prototype_astar.py): "
            "propagación con viento y A* espacio-temporal sobre rejilla de 100 m "
            "con carreteras de OpenStreetMap"
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
