// Escenarios de incendio SIMULADOS (Sierra Bermeja, Málaga). Nada de esto es real: la UI lo
// rotula siempre como "SIMULADO" o "PREDICCIÓN" para no confundirlo con las detecciones FIRMS.
import type { FeatureCollection, LineString, Point, Polygon } from 'geojson';
import type { ScenarioId } from '../store/ui.ts';

export type UnitKind = 'autobomba' | 'helicoptero' | 'dron' | 'mando' | 'ambulancia' | 'brigada';
export type UnitStatus = 'disponible' | 'en ruta' | 'en intervencion' | 'no disponible';

export interface Unit {
  id: string;
  kind: UnitKind;
  name: string;
  status: UnitStatus;
  lon: number;
  lat: number;
  crew: number;
  updated: string;
}

export interface Route {
  name: string;
  /** Punto de reunión al final de la vía */
  meeting: string;
  coords: [number, number][];
}

export interface Scenario {
  id: ScenarioId;
  name: string;
  description: string;
  ignition: [lon: number, lat: number];
  /** Dirección DE la que sopla el viento (grados, 0 = norte) y velocidad */
  windFrom: number;
  windKmh: number;
  camera: { center: [number, number]; zoom: number; bearing: number; pitch: number };
  units: Unit[];
  routes: Route[];
}

const T = '2026-11-14T13:20:00Z';

export const SCENARIOS: Record<ScenarioId, Scenario> = {
  forestal: {
    id: 'forestal',
    name: 'Incendio forestal · Sierra Bermeja',
    description: 'Fuego en ladera de pinar con poniente; avanza hacia el este, hacia la costa.',
    ignition: [-5.205, 36.505],
    windFrom: 280,
    windKmh: 25,
    camera: { center: [-5.19, 36.5], zoom: 11.6, bearing: -15, pitch: 50 },
    units: [
      {
        id: 'BRIF-RO-1',
        kind: 'helicoptero',
        name: 'Helicóptero BRIF Ronda',
        status: 'en intervencion',
        lon: -5.192,
        lat: 36.512,
        crew: 9,
        updated: T,
      },
      {
        id: 'AB-EST-12',
        kind: 'autobomba',
        name: 'Autobomba Estepona 12',
        status: 'en intervencion',
        lon: -5.178,
        lat: 36.493,
        crew: 4,
        updated: T,
      },
      {
        id: 'AB-RON-03',
        kind: 'autobomba',
        name: 'Autobomba Ronda 03',
        status: 'en ruta',
        lon: -5.226,
        lat: 36.538,
        crew: 4,
        updated: T,
      },
      {
        id: 'PMA-1',
        kind: 'mando',
        name: 'Puesto de mando avanzado',
        status: 'disponible',
        lon: -5.188,
        lat: 36.482,
        crew: 6,
        updated: T,
      },
      {
        id: 'DR-07',
        kind: 'dron',
        name: 'Dron de reconocimiento 07',
        status: 'en intervencion',
        lon: -5.222,
        lat: 36.517,
        crew: 1,
        updated: T,
      },
      {
        id: 'BR-GEN-2',
        kind: 'brigada',
        name: 'Brigada Genalguacil 2',
        status: 'disponible',
        lon: -5.236,
        lat: 36.546,
        crew: 7,
        updated: T,
      },
      {
        id: 'SVA-EST',
        kind: 'ambulancia',
        name: 'Ambulancia SVA Estepona',
        status: 'no disponible',
        lon: -5.128,
        lat: 36.424,
        crew: 3,
        updated: T,
      },
    ],
    routes: [
      {
        name: 'Jubrique → Algatocín (A-369)',
        meeting: 'Punto de reunión Algatocín',
        coords: [
          [-5.214, 36.565],
          [-5.232, 36.578],
          [-5.255, 36.581],
          [-5.276, 36.574],
        ],
      },
      {
        name: 'Los Reales → Estepona oeste (MA-8301)',
        meeting: 'Punto de reunión polideportivo Estepona',
        coords: [
          [-5.188, 36.482],
          [-5.196, 36.466],
          [-5.19, 36.447],
          [-5.172, 36.432],
        ],
      },
    ],
  },
  urbano: {
    id: 'urbano',
    name: 'Interfaz urbano-forestal · Estepona',
    description: 'Fuego en el monte junto a urbanizaciones; el levante lo empuja hacia las casas.',
    ignition: [-5.162, 36.462],
    windFrom: 75,
    windKmh: 30,
    camera: { center: [-5.165, 36.45], zoom: 12.4, bearing: 20, pitch: 50 },
    units: [
      {
        id: 'AB-EST-12',
        kind: 'autobomba',
        name: 'Autobomba Estepona 12',
        status: 'en intervencion',
        lon: -5.17,
        lat: 36.457,
        crew: 4,
        updated: T,
      },
      {
        id: 'AB-MAR-05',
        kind: 'autobomba',
        name: 'Autobomba Marbella 05',
        status: 'en ruta',
        lon: -5.13,
        lat: 36.44,
        crew: 4,
        updated: T,
      },
      {
        id: 'PMA-2',
        kind: 'mando',
        name: 'Puesto de mando avanzado',
        status: 'disponible',
        lon: -5.158,
        lat: 36.444,
        crew: 6,
        updated: T,
      },
      {
        id: 'SVA-EST',
        kind: 'ambulancia',
        name: 'Ambulancia SVA Estepona',
        status: 'disponible',
        lon: -5.152,
        lat: 36.43,
        crew: 3,
        updated: T,
      },
      {
        id: 'DR-07',
        kind: 'dron',
        name: 'Dron de reconocimiento 07',
        status: 'en intervencion',
        lon: -5.168,
        lat: 36.466,
        crew: 1,
        updated: T,
      },
      {
        id: 'BRIF-RO-1',
        kind: 'helicoptero',
        name: 'Helicóptero BRIF Ronda',
        status: 'en ruta',
        lon: -5.21,
        lat: 36.5,
        crew: 9,
        updated: T,
      },
    ],
    routes: [
      {
        name: 'Urbanizaciones → Estepona centro (A-7)',
        meeting: 'Punto de reunión puerto de Estepona',
        coords: [
          [-5.175, 36.452],
          [-5.168, 36.44],
          [-5.155, 36.43],
          [-5.143, 36.42],
        ],
      },
      {
        name: 'Valle Romano → Casares costa',
        meeting: 'Punto de reunión Casares costa',
        coords: [
          [-5.185, 36.448],
          [-5.205, 36.432],
          [-5.23, 36.415],
          [-5.255, 36.4],
        ],
      },
    ],
  },
};

const KM_PER_DEG = 111.32;
const rad = (d: number) => (d * Math.PI) / 180;

/** Ruido determinista por celda: bordes irregulares sin aleatoriedad entre recargas. */
function noise(i: number, j: number): number {
  const s = Math.sin(i * 127.1 + j * 311.7) * 43758.5453;
  return s - Math.floor(s);
}

export const CELL_DEG = 0.0025; // ≈ 250 m
export const HORIZON_H = 6;
/** Horas ya transcurridas: lo que arde ahora (simulado); lo posterior es predicción */
export const NOW_H = 1;

/**
 * Propagación elíptica simplificada (modelo de demostración, no operativo): la velocidad es
 * máxima a favor del viento y mínima en contra; cada celda de 250 m guarda su hora de llegada.
 */
export function spread(
  s: Scenario,
): FeatureCollection<
  Polygon,
  { horas: number; fase: 'activo' | 'prediccion'; intensidad: number; altura: number }
> {
  const [lon0, lat0] = s.ignition;
  const head = 0.6 + s.windKmh * 0.045; // km/h en la cabeza
  const e = Math.min(0.85, 0.35 + s.windKmh / 60);
  const towards = rad((s.windFrom + 180) % 360);
  const cosLat = Math.cos(rad(lat0));
  const span = 0.09;
  const features: FeatureCollection<
    Polygon,
    { horas: number; fase: 'activo' | 'prediccion'; intensidad: number; altura: number }
  >['features'] = [];
  const n = Math.round(span / CELL_DEG);
  const baseI = Math.round(lon0 / CELL_DEG);
  const baseJ = Math.round(lat0 / CELL_DEG);
  for (let di = -n; di <= n; di++) {
    for (let dj = -n; dj <= n; dj++) {
      const i = baseI + di;
      const j = baseJ + dj;
      const lon = (i + 0.5) * CELL_DEG;
      const lat = (j + 0.5) * CELL_DEG;
      const x = (lon - lon0) * KM_PER_DEG * cosLat;
      const y = (lat - lat0) * KM_PER_DEG;
      const d = Math.hypot(x, y);
      const theta = Math.atan2(x, y) - towards; // ángulo respecto a la dirección de avance
      const speed = (head * (1 - e)) / (1 - e * Math.cos(theta));
      const hours = (d / speed) * (0.75 + 0.5 * noise(i, j));
      if (hours > HORIZON_H) continue;
      const heat = Math.max(0, 1 - hours / HORIZON_H);
      const intensity = Math.round(200 + heat ** 1.7 * 9800 * (0.78 + noise(i + 11, j + 7) * 0.22));
      const w = i * CELL_DEG;
      const so = j * CELL_DEG;
      features.push({
        type: 'Feature',
        properties: {
          horas: Math.round(hours * 10) / 10,
          fase: hours <= NOW_H ? 'activo' : 'prediccion',
          intensidad: intensity,
          altura: Math.round(4 + heat ** 1.5 * 42),
        },
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [w, so],
              [w + CELL_DEG, so],
              [w + CELL_DEG, so + CELL_DEG],
              [w, so + CELL_DEG],
              [w, so],
            ],
          ],
        },
      });
    }
  }
  return { type: 'FeatureCollection', features };
}

export function routesGeoJson(s: Scenario): FeatureCollection<LineString, { nombre: string }> {
  return {
    type: 'FeatureCollection',
    features: s.routes.map((r) => ({
      type: 'Feature',
      properties: { nombre: r.name },
      geometry: { type: 'LineString', coordinates: r.coords },
    })),
  };
}

export function windGeoJson(s: Scenario): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: [
      { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: s.ignition } },
    ],
  };
}
