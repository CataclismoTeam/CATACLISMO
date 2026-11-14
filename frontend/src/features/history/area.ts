// Área de interés y su traducción a celdas de la rejilla (una celda cuenta si su centro cae dentro).
import type { GridSpec } from '../../data/types.ts';

export type Area =
  | { kind: 'all'; name: string }
  | { kind: 'circle'; name: string; lat: number; lon: number; radiusKm: number }
  | { kind: 'bbox'; name: string; west: number; south: number; east: number; north: number }
  | { kind: 'polygon'; name: string; ring: [lon: number, lat: number][] };

export const SPAIN: Area = { kind: 'all', name: 'España' };

const EARTH_RADIUS_KM = 6371.0088;
const KM_PER_DEGREE = 111.195;
const rad = (deg: number) => (deg * Math.PI) / 180;

export function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const dLat = rad(lat2 - lat1);
  const dLon = rad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(a));
}

function inRing(ring: [number, number][], lon: number, lat: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function contains(area: Area, lat: number, lon: number): boolean {
  switch (area.kind) {
    case 'all':
      return true;
    case 'circle':
      return haversineKm(area.lat, area.lon, lat, lon) <= area.radiusKm;
    case 'bbox':
      return lon >= area.west && lon <= area.east && lat >= area.south && lat <= area.north;
    case 'polygon':
      return inRing(area.ring, lon, lat);
  }
}

/** Rectángulo envolvente del área, para no recorrer toda la rejilla. */
export function bounds(
  area: Area,
  grid: GridSpec,
): { west: number; south: number; east: number; north: number } {
  switch (area.kind) {
    case 'all':
      return { west: grid.oeste, south: grid.sur, east: grid.este, north: grid.norte };
    case 'bbox':
      return area;
    case 'circle': {
      const dLat = area.radiusKm / KM_PER_DEGREE;
      const dLon = dLat / Math.max(0.05, Math.cos(rad(area.lat)));
      return {
        west: area.lon - dLon,
        south: area.lat - dLat,
        east: area.lon + dLon,
        north: area.lat + dLat,
      };
    }
    case 'polygon': {
      const lons = area.ring.map((p) => p[0]);
      const lats = area.ring.map((p) => p[1]);
      return {
        west: Math.min(...lons),
        south: Math.min(...lats),
        east: Math.max(...lons),
        north: Math.max(...lats),
      };
    }
  }
}

export function cellCenter(gid: number, grid: GridSpec): { lat: number; lon: number } {
  const row = Math.floor(gid / grid.columnas);
  const col = gid % grid.columnas;
  return {
    lat: grid.sur + (row + 0.5) * grid.celdaGrados,
    lon: grid.oeste + (col + 0.5) * grid.celdaGrados,
  };
}

export interface AreaCells {
  /** 1 si la celda con datos (por índice en GridData.cells) está dentro del área */
  mask: Uint8Array;
  /** Celdas de la rejilla dentro del área, tengan o no detecciones */
  gridCells: number;
  /** Celdas dentro del área con alguna detección en la serie */
  dataCells: number;
  /** Superficie de las celdas incluidas */
  km2: number;
}

export function areaCells(area: Area, grid: GridSpec, cells: Uint32Array): AreaCells {
  const mask = new Uint8Array(cells.length);
  let dataCells = 0;
  for (let i = 0; i < cells.length; i++) {
    const { lat, lon } = cellCenter(cells[i], grid);
    if (contains(area, lat, lon)) {
      mask[i] = 1;
      dataCells++;
    }
  }

  const box = bounds(area, grid);
  const deg = grid.celdaGrados;
  const rowFrom = Math.max(0, Math.floor((box.south - grid.sur) / deg));
  const rowTo = Math.min(grid.filas - 1, Math.floor((box.north - grid.sur) / deg));
  const colFrom = Math.max(0, Math.floor((box.west - grid.oeste) / deg));
  const colTo = Math.min(grid.columnas - 1, Math.floor((box.east - grid.oeste) / deg));
  let gridCells = 0;
  let km2 = 0;
  for (let row = rowFrom; row <= rowTo; row++) {
    const lat = grid.sur + (row + 0.5) * deg;
    const cellKm2 = (deg * KM_PER_DEGREE) ** 2 * Math.cos(rad(lat));
    for (let col = colFrom; col <= colTo; col++) {
      if (contains(area, lat, grid.oeste + (col + 0.5) * deg)) {
        gridCells++;
        km2 += cellKm2;
      }
    }
  }
  return { mask, gridCells, dataCells, km2 };
}

export function describeArea(area: Area): string {
  switch (area.kind) {
    case 'all':
      return area.name;
    case 'circle':
      return `${area.name}: radio ${area.radiusKm} km en ${area.lat.toFixed(4)}, ${area.lon.toFixed(4)}`;
    case 'bbox':
      return `${area.name}: O ${area.west.toFixed(3)}, S ${area.south.toFixed(3)}, E ${area.east.toFixed(3)}, N ${area.north.toFixed(3)}`;
    case 'polygon':
      return `${area.name}: polígono de ${area.ring.length} vértices`;
  }
}
