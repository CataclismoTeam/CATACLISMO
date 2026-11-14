// Detecciones REALES de FIRMS (últimos 90 días) como cuadrados del tamaño del píxel del sensor:
// 375 m en VIIRS y 1 km en MODIS. Así se ve la huella real de cada detección, no un punto.
import type { FeatureCollection, Polygon } from 'geojson';

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
  geojson: FeatureCollection<Polygon, DetectionProps>;
}

const CONF = ['baja', 'nominal', 'alta'];

export async function loadDetections(): Promise<Detections> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/detections-recent-v1.json`);
  if (!response.ok) throw new Error('detecciones no disponibles');
  const d = (await response.json()) as RecentFile;
  const features: Detections['geojson']['features'] = d.lat.map((lat, i) => {
    const half = (d.sensor[i] === 0 ? 0.5 : 0.1875) / 111.32;
    const halfLon = half / Math.cos((lat * Math.PI) / 180);
    const lon = d.lon[i];
    return {
      type: 'Feature',
      properties: {
        sensor: d.sensor[i] === 0 ? 'MODIS' : 'VIIRS',
        frp: d.frp[i],
        fecha: new Date(d.t[i] * 1000).toISOString().slice(0, 16).replace('T', ' ') + ' UTC',
        confianza: CONF[d.conf[i]] ?? 'nominal',
        provisional: d.provisional[i] === 1,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [lon - halfLon, lat - half],
            [lon + halfLon, lat - half],
            [lon + halfLon, lat + half],
            [lon - halfLon, lat + half],
            [lon - halfLon, lat - half],
          ],
        ],
      },
    };
  });
  return { from: d.desde, to: d.hasta, geojson: { type: 'FeatureCollection', features } };
}
