// Detecciones REALES de FIRMS (últimos 90 días). Se pintan como superficie de calor ponderada
// por la potencia radiativa (FRP), con el contorno del incendio encima: no como cuadrados.
import type { FeatureCollection, Point } from 'geojson';

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
