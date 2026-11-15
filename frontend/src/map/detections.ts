// Detecciones REALES de FIRMS (últimos 90 días). Se pintan en celdas de 250 m, igual que el
// incendio simulado, con color según la potencia radiativa (FRP).
import type { FeatureCollection, Point, Polygon } from 'geojson';

interface RecentFile {
  desde: string;
  hasta: string;
  lat: number[];
  lon: number[];
  t: number[];
  sensor: number[];
  conf: number[];
  frp: number[];
  provisional: number[];
}

export interface DetectionProps {
  sensor: 'MODIS' | 'VIIRS';
  frp: number;
  fecha: string;
  confianza: string;
  provisional: boolean;
}

export interface Detections {
  from: string;
  to: string;
  /** Centro de cada detección: alimenta la superficie de calor (no cuadrados) */
  geojson: FeatureCollection<Point, DetectionProps>;
}

const CONF = ['baja', 'nominal', 'alta'];

export async function loadDetections(): Promise<Detections> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/detections-recent-v1.json`);
  if (!response.ok) throw new Error('detecciones no disponibles');
  const d = (await response.json()) as RecentFile;
  const features: Detections['geojson']['features'] = d.lat.map((lat, i) => ({
    type: 'Feature',
    properties: {
      sensor: d.sensor[i] === 0 ? 'MODIS' : 'VIIRS',
      frp: d.frp[i],
      fecha: new Date(d.t[i] * 1000).toISOString().slice(0, 16).replace('T', ' ') + ' UTC',
      confianza: CONF[d.conf[i]] ?? 'nominal',
      provisional: d.provisional[i] === 1,
    },
    geometry: { type: 'Point', coordinates: [d.lon[i], lat] },
  }));
  return { from: d.desde, to: d.hasta, geojson: { type: 'FeatureCollection', features } };
}

/** Lado de celda, el mismo que el incendio simulado (≈ 250 m). */
const CELL = 0.0025;
/** Días sin detección para dar una celda por apagada: el mismo criterio que los incendios
 * (`diasSinDeteccionInactivo` de tools/build-hotspots). */
export const ACTIVE_DAYS = 3;
const DAY_MS = 86_400_000;

/**
 * Celdas de 250 m con fuego real: cada detección marca las celdas que cubre su píxel y cada una guarda
 * la potencia máxima. Mismo aspecto que el incendio simulado; el color dice que es real.
 */
export function fireCells(
  detections: Detections,
  activeDays = ACTIVE_DAYS,
): FeatureCollection<Polygon, { frp: number; detecciones: number; activo: boolean }> {
  const cells = new Map<string, { i: number; j: number; frp: number; n: number; last: string }>();
  for (const f of detections.geojson.features) {
    const day = f.properties.fecha.slice(0, 10);
    const [lon, lat] = f.geometry.coordinates;
    // Huella del píxel del sensor: VIIRS ~375 m, MODIS ~1 km de lado
    const halfKm = f.properties.sensor === 'MODIS' ? 0.5 : 0.1875;
    const dLat = halfKm / 111.32;
    const dLon = dLat / Math.cos((lat * Math.PI) / 180);
    for (let i = Math.floor((lon - dLon) / CELL); i <= Math.floor((lon + dLon) / CELL); i++) {
      for (let j = Math.floor((lat - dLat) / CELL); j <= Math.floor((lat + dLat) / CELL); j++) {
        const key = `${i}:${j}`;
        const cell = cells.get(key);
        if (cell) {
          cell.frp = Math.max(cell.frp, f.properties.frp);
          cell.n += 1;
          if (day > cell.last) cell.last = day;
        } else cells.set(key, { i, j, frp: f.properties.frp, n: 1, last: day });
      }
    }
  }
  const end = Date.parse(detections.to);
  return {
    type: 'FeatureCollection',
    features: [...cells.values()].map(({ i, j, frp, n, last }) => {
      const w = i * CELL;
      const s = j * CELL;
      return {
        type: 'Feature',
        // Activa si tuvo fuego en los últimos días del dato; si no, ya es ceniza
        properties: { frp, detecciones: n, activo: (end - Date.parse(last)) / DAY_MS < activeDays },
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [w, s],
              [w + CELL, s],
              [w + CELL, s + CELL],
              [w, s + CELL],
              [w, s],
            ],
          ],
        },
      };
    }),
  };
}
