// Simulaciones de incendio (SIMULADAS) repartidas por España. Nada de esto es real: la UI lo
// rotula siempre como "SIMULADO" o "PREDICCIÓN" para no confundirlo con las detecciones FIRMS.
// Las definiciones viven en scenarios.json, que también lee el preproceso de vías de escape.
import type { FeatureCollection, LineString, Point, Polygon } from 'geojson';
import definitions from './scenarios.json';

export type Domain = 'aire' | 'tierra' | 'mar';
export type UnitKind =
  | 'autobomba'
  | 'nodriza'
  | 'maquinaria'
  | 'brigada'
  | 'mando'
  | 'ambulancia'
  | 'helicoptero'
  | 'avion'
  | 'dron'
  | 'embarcacion';
export type UnitStatus = 'disponible' | 'en ruta' | 'en intervencion' | 'no disponible';

export interface Unit {
  id: string;
  kind: UnitKind;
  domain: Domain;
  /** Solo tierra: grupo operativo con canal de radio propio */
  group?: string;
  name: string;
  status: UnitStatus;
  lon: number;
  lat: number;
  crew: number;
  updated: string;
}

/** Vía de escape calculada por el algoritmo del equipo (escape-routes-v1.json) */
export interface Route {
  nombre: string;
  desde: string;
  refugio: string;
  coords: [number, number][];
  distanciaKm: number;
  tiempoMin: number;
  margenMin: number | null;
  llegadaFuegoMin: number;
}

interface Definition {
  id: string;
  kind: 'forestal' | 'urbano';
  name: string;
  comunidad: string;
  provincia: string;
  description: string;
  ignition: [number, number];
  windFrom: number;
  windKmh: number;
  camera: { center: [number, number]; zoom: number; bearing: number; pitch: number };
  /** Punto de mar cercano: solo las simulaciones costeras tienen medios marítimos */
  sea?: [number, number];
}

export interface Scenario extends Definition {
  units: Unit[];
}

export const GROUPS = [
  'Mando',
  'Grupo 1 · Ataque directo',
  'Grupo 2 · Flanco',
  'Grupo 3 · Defensa de núcleos',
  'Sanitario y logística',
] as const;

const T = '2026-11-14T13:20:00Z';

type Template = [
  domain: Domain,
  kind: UnitKind,
  code: string,
  name: string,
  status: UnitStatus,
  crew: number,
  /** Posición en km: x a lo ancho del frente, y a favor del viento desde el foco */
  at: [number, number],
  group?: (typeof GROUPS)[number],
];

// Plantilla del dispositivo: tierra concentra la mayoría de medios, organizados en grupos
const TEMPLATE: Template[] = [
  ['aire', 'helicoptero', 'HT-1', 'Helicóptero de extinción', 'en intervencion', 9, [0.6, 1.2]],
  ['aire', 'helicoptero', 'HT-2', 'Helicóptero de transporte de brigada', 'en ruta', 7, [-2.5, -3]],
  ['aire', 'avion', 'AA-1', 'Avión anfibio', 'en intervencion', 2, [-0.8, 2]],
  ['aire', 'dron', 'DR-1', 'Dron de reconocimiento', 'en intervencion', 1, [1.4, 0.4]],
  ['tierra', 'mando', 'PMA-1', 'Puesto de mando avanzado', 'disponible', 6, [0, -2.6], 'Mando'],
  [
    'tierra',
    'autobomba',
    'AB-11',
    'Autobomba forestal',
    'en intervencion',
    4,
    [0.9, 1.6],
    'Grupo 1 · Ataque directo',
  ],
  [
    'tierra',
    'autobomba',
    'AB-12',
    'Autobomba forestal',
    'en intervencion',
    4,
    [-0.9, 1.5],
    'Grupo 1 · Ataque directo',
  ],
  [
    'tierra',
    'brigada',
    'BR-11',
    'Brigada de tierra',
    'en intervencion',
    7,
    [0.3, 1.9],
    'Grupo 1 · Ataque directo',
  ],
  [
    'tierra',
    'autobomba',
    'AB-21',
    'Autobomba forestal',
    'en intervencion',
    4,
    [2.2, 0.6],
    'Grupo 2 · Flanco',
  ],
  [
    'tierra',
    'maquinaria',
    'MQ-21',
    'Bulldozer para cortafuegos',
    'en ruta',
    2,
    [2.8, -0.4],
    'Grupo 2 · Flanco',
  ],
  [
    'tierra',
    'brigada',
    'BR-21',
    'Brigada de tierra',
    'disponible',
    7,
    [-2.2, 0.4],
    'Grupo 2 · Flanco',
  ],
  [
    'tierra',
    'autobomba',
    'AB-31',
    'Autobomba urbana',
    'en ruta',
    5,
    [0.4, 3.6],
    'Grupo 3 · Defensa de núcleos',
  ],
  [
    'tierra',
    'autobomba',
    'AB-32',
    'Autobomba urbana',
    'disponible',
    5,
    [-1.4, 3.8],
    'Grupo 3 · Defensa de núcleos',
  ],
  [
    'tierra',
    'nodriza',
    'ND-1',
    'Camión nodriza (agua)',
    'disponible',
    2,
    [1.2, -1.6],
    'Sanitario y logística',
  ],
  [
    'tierra',
    'ambulancia',
    'SVA-1',
    'Ambulancia de soporte vital avanzado',
    'disponible',
    3,
    [-0.6, -3.2],
    'Sanitario y logística',
  ],
  [
    'tierra',
    'ambulancia',
    'SVB-1',
    'Ambulancia de soporte vital básico',
    'no disponible',
    2,
    [0.8, -3.4],
    'Sanitario y logística',
  ],
];

const KM = 111.32;

function place(def: Definition, [x, y]: [number, number]): [number, number] {
  // y a favor del viento, x perpendicular (a la derecha del avance)
  const towards = ((def.windFrom + 180) % 360) * (Math.PI / 180);
  const east = y * Math.sin(towards) + x * Math.cos(towards);
  const north = y * Math.cos(towards) - x * Math.sin(towards);
  const [lon0, lat0] = def.ignition;
  return [lon0 + east / (KM * Math.cos((lat0 * Math.PI) / 180)), lat0 + north / KM];
}

function unitsFor(def: Definition): Unit[] {
  const units: Unit[] = TEMPLATE.map(([domain, kind, code, name, status, crew, at, group]) => {
    const [lon, lat] = place(def, at);
    return { id: code, kind, domain, group, name, status, crew, lon, lat, updated: T };
  });
  if (def.sea) {
    units.push(
      {
        id: 'SM-1',
        kind: 'embarcacion',
        domain: 'mar',
        name: 'Salvamar (Salvamento Marítimo)',
        status: 'en ruta',
        crew: 4,
        lon: def.sea[0],
        lat: def.sea[1],
        updated: T,
      },
      {
        id: 'SM-2',
        kind: 'embarcacion',
        domain: 'mar',
        name: 'Embarcación de evacuación costera',
        status: 'disponible',
        crew: 6,
        lon: def.sea[0] + 0.02,
        lat: def.sea[1] - 0.01,
        updated: T,
      },
    );
  }
  return units;
}

export const SCENARIO_LIST: Scenario[] = (definitions as Definition[]).map((d) => ({
  ...d,
  units: unitsFor(d),
}));

export const SCENARIOS: Record<string, Scenario> = Object.fromEntries(
  SCENARIO_LIST.map((s) => [s.id, s]),
);

export const DEFAULT_SCENARIO = SCENARIO_LIST[0].id;

export const DOMAIN_LABEL: Record<Domain, string> = { aire: 'Aire', tierra: 'Tierra', mar: 'Mar' };

export interface Channel {
  id: string;
  domain: Domain;
  name: string;
  /** Indicativos que escuchan el canal */
  members: string[];
  last: string;
}

/**
 * Canales de radio del dispositivo (SIMULADOS): uno de aire, un canal general de tierra donde
 * hablan todos los medios terrestres, uno por grupo de tierra y uno de mar si hay medios marítimos.
 */
export function channelsFor(s: Scenario): Channel[] {
  const of = (d: Domain) => s.units.filter((u) => u.domain === d);
  const land = of('tierra');
  const channels: Channel[] = [
    {
      id: 'aire',
      domain: 'aire',
      name: 'Coordinación aérea',
      members: of('aire').map((u) => u.id),
      last: 'HT-1: descarga en la cabeza del fuego, vuelvo a cargar agua',
    },
    {
      id: 'tierra-general',
      domain: 'tierra',
      name: 'General Tierra',
      members: land.map((u) => u.id),
      last: 'PMA-1: todos los grupos, mantengan las vías de escape despejadas',
    },
    ...GROUPS.map((g, i) => ({
      id: `tierra-${i}`,
      domain: 'tierra' as const,
      name: g,
      members: land.filter((u) => u.group === g).map((u) => u.id),
      last: [
        'PMA-1: relevo de turno a las 20:00 UTC',
        'AB-11: atacando la cabeza, necesitamos agua en 15 min',
        'MQ-21: abriendo cortafuegos en el flanco derecho',
        'AB-31: en posición junto a las primeras casas',
        'SVA-1: sin heridos por ahora, en espera en el PMA',
      ][i],
    })),
  ];
  const sea = of('mar');
  if (sea.length) {
    channels.push({
      id: 'mar',
      domain: 'mar',
      name: 'Salvamento marítimo',
      members: sea.map((u) => u.id),
      last: 'SM-1: preparados para evacuar por mar desde la playa',
    });
  }
  return channels;
}

export interface EscapeRoutes {
  metodo: string;
  atribucion: string;
  escenarios: Record<string, { rutas: Route[]; nucleos: number }>;
}

export async function loadEscapeRoutes(): Promise<EscapeRoutes> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/escape-routes-v1.json`);
  if (!response.ok) throw new Error('vías de escape no disponibles');
  return (await response.json()) as EscapeRoutes;
}

const KM_PER_DEG = KM;
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
  return spreadFrom(s.ignition, s.windFrom, s.windKmh);
}

/** Misma propagación desde un punto cualquiera: la usan también los incendios reales. */
export function spreadFrom(
  ignition: [number, number],
  windFrom: number,
  windKmh: number,
): FeatureCollection<
  Polygon,
  { horas: number; fase: 'activo' | 'prediccion'; intensidad: number; altura: number }
> {
  const [lon0, lat0] = ignition;
  const head = 0.6 + windKmh * 0.045; // km/h en la cabeza
  const e = Math.min(0.85, 0.35 + windKmh / 60);
  const towards = rad((windFrom + 180) % 360);
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

export function routesGeoJson(routes: Route[]): FeatureCollection<LineString, { nombre: string }> {
  return {
    type: 'FeatureCollection',
    features: routes.map((r) => ({
      type: 'Feature',
      properties: { nombre: r.nombre },
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
