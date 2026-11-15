// Del calendario al mapa: la rejilla de 5 km de un mes y el contorno del área de interés.
import type { FeatureCollection, Polygon } from 'geojson';
import type { GridData, GridSpec } from '../../data/types.ts';
import { cellCenter, type Area } from './area.ts';

/** Celdas de 5 km con detecciones en el mes `mi` (0 = enero del año inicial), con su valor h. */
export function monthCells(
  grid: GridData,
  spec: GridSpec,
  startYear: number,
  mi: number,
): FeatureCollection<Polygon, { h: number }> {
  const year = startYear + Math.floor(mi / 12);
  const month = mi % 12;
  const chunk = grid.years.find((y) => y.year === year);
  const features: FeatureCollection<Polygon, { h: number }>['features'] = [];
  if (!chunk) return { type: 'FeatureCollection', features };
  const half = spec.celdaGrados / 2;
  for (let i = 0; i < chunk.n; i++) {
    if (chunk.month[i] !== month || !(chunk.h[i] > 0)) continue;
    const { lat, lon } = cellCenter(grid.cells[chunk.cell[i]], spec);
    const [w, s, e, n] = [lon - half, lat - half, lon + half, lat + half];
    features.push({
      type: 'Feature',
      properties: { h: Math.round(chunk.h[i] * 10) / 10 },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [w, s],
            [e, s],
            [e, n],
            [w, n],
            [w, s],
          ],
        ],
      },
    });
  }
  return { type: 'FeatureCollection', features };
}

const KM_PER_DEGREE = 111.195;

/** Anillo del área (lon, lat), o null para «toda España». El círculo va en 64 lados. */
export function areaRing(area: Area): [number, number][] | null {
  switch (area.kind) {
    case 'all':
      return null;
    case 'bbox':
      return [
        [area.west, area.south],
        [area.east, area.south],
        [area.east, area.north],
        [area.west, area.north],
        [area.west, area.south],
      ];
    case 'polygon':
      return [...area.ring, area.ring[0]];
    case 'circle': {
      const dLat = area.radiusKm / KM_PER_DEGREE;
      const dLon = dLat / Math.cos((area.lat * Math.PI) / 180);
      return Array.from({ length: 65 }, (_, i) => {
        const a = (i / 64) * 2 * Math.PI;
        return [area.lon + dLon * Math.sin(a), area.lat + dLat * Math.cos(a)];
      });
    }
  }
}

/** Rectángulo envolvente [oeste, sur, este, norte] de un anillo. */
export function ringBbox(ring: [number, number][]): [number, number, number, number] {
  const lons = ring.map((p) => p[0]);
  const lats = ring.map((p) => p[1]);
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}
