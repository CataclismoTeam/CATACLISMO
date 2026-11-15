// Geometría de la regla del mapa: longitud de una línea y superficie de un polígono cerrado.
import { haversineKm } from '../features/history/area.ts';

export type LonLat = [lon: number, lat: number];

/** Longitud en km de la línea (y del tramo de cierre si está cerrada). */
export function lengthKm(points: LonLat[], closed = false): number {
  const path = closed && points.length > 2 ? [...points, points[0]] : points;
  let km = 0;
  for (let i = 1; i < path.length; i++) {
    km += haversineKm(path[i - 1][1], path[i - 1][0], path[i][1], path[i][0]);
  }
  return km;
}

const EARTH_RADIUS_KM = 6371.0088;
const rad = (d: number) => (d * Math.PI) / 180;

/**
 * Superficie en km² de un polígono pequeño (unas decenas de km): proyección equirrectangular
 * centrada en su latitud media y fórmula del área de Gauss.
 */
export function areaKm2(points: LonLat[]): number {
  if (points.length < 3) return 0;
  const lat0 = rad(points.reduce((sum, p) => sum + p[1], 0) / points.length);
  const xy = points.map(([lon, lat]) => [
    EARTH_RADIUS_KM * rad(lon) * Math.cos(lat0),
    EARTH_RADIUS_KM * rad(lat),
  ]);
  let twice = 0;
  for (let i = 0; i < xy.length; i++) {
    const [x1, y1] = xy[i];
    const [x2, y2] = xy[(i + 1) % xy.length];
    twice += x1 * y2 - x2 * y1;
  }
  return Math.abs(twice) / 2;
}

const decimal = (v: number, digits: number) =>
  v.toLocaleString('es-ES', { maximumFractionDigits: digits, minimumFractionDigits: 0 });

/** «850 m», «3,25 km» o «42 km». */
export function formatLength(km: number): string {
  if (km < 1) return `${Math.round(km * 1000)} m`;
  return `${decimal(km, km < 10 ? 2 : 1)} km`;
}

/** Hectáreas por debajo de 1 km² (1 km² = 100 ha); km² por encima. */
export function formatArea(km2: number): string {
  if (km2 < 1) return `${decimal(km2 * 100, 1)} ha`;
  return `${decimal(km2, km2 < 10 ? 2 : 1)} km²`;
}
