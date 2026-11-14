import { SPAIN, type Area } from './area.ts';

/** Áreas de acceso rápido. La zona de demostración es la Sierra de Málaga. */
export const AREA_PRESETS: Area[] = [
  SPAIN,
  { kind: 'circle', name: 'Sierra Bermeja (Málaga)', lat: 36.49, lon: -5.2, radiusKm: 25 },
  { kind: 'bbox', name: 'Andalucía', west: -7.55, south: 35.95, east: -1.6, north: 38.75 },
  { kind: 'bbox', name: 'Galicia', west: -9.35, south: 41.8, east: -6.7, north: 43.8 },
  { kind: 'bbox', name: 'Canarias', west: -18.2, south: 27.6, east: -13.3, north: 29.5 },
];
