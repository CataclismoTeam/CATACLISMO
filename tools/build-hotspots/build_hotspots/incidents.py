"""Incendios a partir de detecciones: agrupación espacio-temporal, contorno y comunidad autónoma.

Un incendio es un grupo de detecciones conectadas: dos detecciones van juntas si están a menos
de `link_km` y separadas menos de `link_days` días (encadenando, como un frente que avanza).
El contorno es la unión de las huellas de píxel (375 m VIIRS, 1 km MODIS) suavizada con un
cierre morfológico, así que sigue la forma real del área afectada y no una rejilla.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
from shapely import STRtree, box, points
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union

KM_PER_DEG = 111.32

# Nombres oficiales (la fuente de límites los trae sin tildes)
CCAA_NAMES = {
    "Andalucia": "Andalucía",
    "Aragon": "Aragón",
    "Asturias": "Principado de Asturias",
    "Baleares": "Illes Balears",
    "Canarias": "Canarias",
    "Cantabria": "Cantabria",
    "Castilla-Leon": "Castilla y León",
    "Castilla-La Mancha": "Castilla-La Mancha",
    "Cataluña": "Cataluña",
    "Ceuta": "Ceuta",
    "Extremadura": "Extremadura",
    "Galicia": "Galicia",
    "La Rioja": "La Rioja",
    "Madrid": "Comunidad de Madrid",
    "Melilla": "Melilla",
    "Murcia": "Región de Murcia",
    "Navarra": "Comunidad Foral de Navarra",
    "Pais Vasco": "País Vasco",
    "Valencia": "Comunitat Valenciana",
}


@dataclass(frozen=True)
class IncidentConfig:
    link_km: float = 2.0
    link_days: int = 3
    min_detections: int = 3
    # Días sin detecciones a partir de los cuales se da el foco por inactivo (no "extinguido":
    # eso solo puede decirlo quien está en el terreno)
    active_days: int = 3


class Regions:
    """Comunidades y provincias con búsqueda por punto (la más cercana si cae en el mar)."""

    def __init__(self, ccaa_path: Path, prov_path: Path) -> None:
        def load(path: Path) -> tuple[list[str], list]:
            data = json.loads(path.read_text(encoding="utf-8"))
            names = [f["properties"]["name"] for f in data["features"]]
            geoms = [shape(f["geometry"]) for f in data["features"]]
            return names, geoms

        self.ccaa_names, self.ccaa = load(ccaa_path)
        self.prov_names, self.prov = load(prov_path)
        self.ccaa_tree = STRtree(self.ccaa)
        self.prov_tree = STRtree(self.prov)

    @staticmethod
    def _find(tree: STRtree, geoms: list, lon: float, lat: float) -> int:
        pt = points(lon, lat)
        hits = tree.query(pt, predicate="intersects")
        if len(hits):
            return int(hits[0])
        # Detección en la costa o en el mar: la región más cercana
        return int(tree.nearest(pt))

    def ccaa_of(self, lon: float, lat: float) -> str:
        name = self.ccaa_names[self._find(self.ccaa_tree, self.ccaa, lon, lat)]
        return CCAA_NAMES.get(name, name)

    def province_of(self, lon: float, lat: float) -> str:
        return self.prov_names[self._find(self.prov_tree, self.prov, lon, lat)]


def _clusters(lat: np.ndarray, lon: np.ndarray, day: np.ndarray, cfg: IncidentConfig) -> np.ndarray:
    """Etiqueta de grupo por detección (unión-búsqueda con rejilla espacial)."""
    n = len(lat)
    parent = np.arange(n)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cell = cfg.link_km / KM_PER_DEG
    cos = np.cos(np.radians(np.mean(lat))) if n else 1.0
    gx = np.floor(lon * cos / cell).astype(np.int64)
    gy = np.floor(lat / cell).astype(np.int64)
    buckets: dict[tuple[int, int], list[int]] = {}
    for i in range(n):
        buckets.setdefault((gx[i], gy[i]), []).append(i)
    for i in range(n):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in buckets.get((gx[i] + dx, gy[i] + dy), ()):
                    if j <= i or abs(int(day[i]) - int(day[j])) > cfg.link_days:
                        continue
                    dkm = np.hypot(
                        (lon[i] - lon[j]) * KM_PER_DEG * cos, (lat[i] - lat[j]) * KM_PER_DEG
                    )
                    if dkm <= cfg.link_km:
                        ri, rj = find(i), find(j)
                        if ri != rj:
                            parent[rj] = ri
    return np.array([find(i) for i in range(n)])


def _footprint(lon: float, lat: float, sensor: str) -> Polygon:
    half = (0.5 if sensor == "MODIS" else 0.1875) / KM_PER_DEG
    half_lon = half / np.cos(np.radians(lat))
    return box(lon - half_lon, lat - half, lon + half_lon, lat + half)


def _outline(group: pl.DataFrame) -> tuple[Polygon | MultiPolygon, float]:
    union = unary_union(
        [_footprint(x, y, s) for x, y, s in group.select("lon", "lat", "sensor").iter_rows()]
    )
    # Cierre morfológico (~300 m): une huellas vecinas y redondea la escalera de los píxeles
    r = 0.3 / KM_PER_DEG
    smooth = union.buffer(r, quad_segs=4).buffer(-r, quad_segs=4).simplify(r / 6)
    lat0 = float(group["lat"].mean())
    km2 = union.area * KM_PER_DEG**2 * float(np.cos(np.radians(lat0)))
    return smooth, km2


def _round_coords(geom: dict) -> dict:
    def walk(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            return [round(c[0], 4), round(c[1], 4)]
        return [walk(x) for x in c]

    return {"type": geom["type"], "coordinates": walk(geom["coordinates"])}


def build_incidents(
    df: pl.DataFrame, regions: Regions, since: date, cfg: IncidentConfig | None = None
) -> dict:
    """Incendios con detecciones desde `since`, ordenados por actividad (FRP total)."""
    cfg = cfg or IncidentConfig()
    recent = df.filter(pl.col("date") >= since).sort("date", "minute")
    if recent.is_empty():
        return {"incendios": [], "comunidades": []}
    last_day = recent["date"].max()
    epoch = date(1970, 1, 1)
    days = np.array([(d - epoch).days for d in recent["date"]])
    labels = _clusters(recent["lat"].to_numpy(), recent["lon"].to_numpy(), days, cfg)
    recent = recent.with_columns(pl.Series("grupo", labels))

    incidents = []
    for _, group in recent.group_by("grupo", maintain_order=True):
        if group.height < cfg.min_detections:
            continue
        outline, km2 = _outline(group)
        # Centro: la detección de mayor potencia (donde más arde), no el centroide geométrico
        hottest = group.sort("frp", descending=True).row(0, named=True)
        first, last = group["date"].min(), group["date"].max()
        incidents.append(
            {
                "comunidad": regions.ccaa_of(hottest["lon"], hottest["lat"]),
                "provincia": regions.province_of(hottest["lon"], hottest["lat"]),
                "lon": round(hottest["lon"], 4),
                "lat": round(hottest["lat"], 4),
                "bbox": [round(v, 4) for v in outline.bounds],
                "desde": first.isoformat(),
                "hasta": last.isoformat(),
                "activo": (last_day - last).days < cfg.active_days,
                "detecciones": group.height,
                "sensores": sorted(set(group["sensor"])),
                "frpMax": round(float(group["frp"].max()), 1),
                "frpTotal": round(float(group["frp"].sum()), 1),
                "areaKm2": round(km2, 2),
                "contorno": _round_coords(mapping(outline)),
            }
        )
    incidents.sort(key=lambda x: x["frpTotal"], reverse=True)
    for i, inc in enumerate(incidents, start=1):
        inc["id"] = f"INC-{i:03d}"
    return {
        "desde": since.isoformat(),
        "hasta": last_day.isoformat(),
        "criterio": {
            "distanciaKm": cfg.link_km,
            "dias": cfg.link_days,
            "minDetecciones": cfg.min_detections,
            "diasSinDeteccionInactivo": cfg.active_days,
        },
        "comunidades": sorted({i["comunidad"] for i in incidents}),
        "incendios": incidents,
    }
