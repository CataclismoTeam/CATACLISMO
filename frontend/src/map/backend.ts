// Capas del backend: CATA (predicción neuronal por celdas de 1 km), LUCIA (vías de escape y
// puntos de encuentro) y JULI (equipos en terreno en vivo). Llegan como GeoJSON WGS84.
import type { ExpressionSpecification, GeoJSONSource, Map as MapLibre } from 'maplibre-gl';
import type { Feature, FeatureCollection, Geometry } from 'geojson';
import type { LayerId } from '../store/ui.ts';
import { ASH_COLOR } from './overlays.ts';

export type FireCategory = 'BURNING_ACTIVE' | 'ALREADY_BURNED' | 'THRESHOLD_BUFFER_UNSAFE';

export interface LuciaZone {
  zone_id: string;
  reference_date: string;
  predicted_date: string;
  routes_generated: number;
  meeting_points_safe: number;
  cells_burning_active: number;
  cells_already_burned: number;
}

export interface LuciaCollection extends FeatureCollection<Geometry, Record<string, unknown>> {
  metadata?: {
    created_at?: string;
    cell_size_m?: number;
    tensorflow_model_used?: boolean;
    total_routes_generated?: number;
    total_meeting_points?: number;
    zones?: LuciaZone[];
  };
}

export interface ProofOfLifeAlert {
  operator_id: string;
  callsign?: string;
  name?: string;
  summary?: string;
}

export interface JuliCollection extends FeatureCollection<Geometry, Record<string, unknown>> {
  metadata?: {
    generated_at?: string;
    total_teams?: number;
    total_operators?: number;
    proof_of_life?: { active_alerts_count?: number; alerts?: ProofOfLifeAlert[] };
  };
}

/** Colores de las celdas de CATA: la zona ya quemada usa la misma ceniza que los reales. */
export const CATA_COLORS: Record<FireCategory, [color: string, opacity: number]> = {
  BURNING_ACTIVE: ['#ef4444', 0.6],
  ALREADY_BURNED: [ASH_COLOR, 0.6],
  THRESHOLD_BUFFER_UNSAFE: ['#f97316', 0.35],
};
export const LUCIA_HUMAN = '#10b981';
export const LUCIA_ANIMAL = '#38bdf8';
export const MEETING_COLOR = '#22c55e';
export const ORIGIN_COLOR = '#f59e0b';
/** Estado del operario de JULI → color del punto */
export const JULI_STATUS: Record<string, [color: string, label: string]> = {
  en_terreno: ['#22c55e', 'En terreno'],
  en_ruta: ['#3b82f6', 'En ruta'],
  en_descanso: ['#a3a3a3', 'En descanso'],
  alerta: ['#ef4444', 'Alerta'],
  inactivo: ['#6b7280', 'Inactivo'],
};

/** Capas que se pueden pulsar para ver su ficha */
export const BACKEND_CLICKABLE = ['be-juli', 'be-puntos', 'be-ruta', 'be-cata-fill'];

type Props = Record<string, unknown>;
const ofType = (fc: FeatureCollection<Geometry, Props> | undefined, ...types: string[]) =>
  fc?.features.filter((f) => types.includes(String(f.properties?.feature_type))) ?? [];

/** Encuadre [oeste, sur, este, norte] de unas features (puntos, líneas o polígonos). */
export function bboxOf(
  features: Feature<Geometry, Props>[],
): [number, number, number, number] | undefined {
  let w = Infinity;
  let s = Infinity;
  let e = -Infinity;
  let n = -Infinity;
  const visit = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === 'number' && typeof c[1] === 'number') {
      w = Math.min(w, c[0]);
      e = Math.max(e, c[0]);
      s = Math.min(s, c[1]);
      n = Math.max(n, c[1]);
    } else if (Array.isArray(c)) c.forEach(visit);
  };
  for (const f of features) if ('coordinates' in f.geometry) visit(f.geometry.coordinates);
  return Number.isFinite(w) ? [w, s, e, n] : undefined;
}

export const luciaBbox = (fc?: LuciaCollection) =>
  bboxOf(ofType(fc, 'fire_cell', 'evacuation_route', 'meeting_point'));
export const juliBbox = (fc?: JuliCollection) => bboxOf(ofType(fc, 'field_operator'));

/** Operarios con alerta de prueba de vida activa */
export function alertedOperators(fc?: JuliCollection): Set<string> {
  return new Set((fc?.metadata?.proof_of_life?.alerts ?? []).map((a) => a.operator_id));
}

function upsert(map: MapLibre, id: string, data: FeatureCollection) {
  const source = map.getSource(id);
  if (source && 'setData' in source) (source as GeoJSONSource).setData(data);
  else map.addSource(id, { type: 'geojson', data });
}

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

/** Instala o actualiza las capas del backend. Sin datos, quedan vacías. */
export function installBackendLayers(
  map: MapLibre,
  lucia: LuciaCollection | undefined,
  juli: JuliCollection | undefined,
  visible: Record<LayerId, boolean>,
) {
  const alerted = alertedOperators(juli);
  upsert(map, 'be-lucia', lucia ?? EMPTY);
  upsert(map, 'be-juli', {
    type: 'FeatureCollection',
    // La alerta va en cada operario para poder pintarla con una expresión
    features: ofType(juli, 'field_operator', 'field_team_formation').map((f) => ({
      ...f,
      properties: { ...f.properties, alerta: alerted.has(String(f.properties?.operator_id)) },
    })),
  });
  const vis = (id: LayerId) => (visible[id] ? 'visible' : 'none') as 'visible' | 'none';
  const category: ExpressionSpecification = ['get', 'fire_zone_category'];
  if (!map.getLayer('be-cata-fill')) {
    map.addLayer({
      id: 'be-cata-fill',
      type: 'fill',
      source: 'be-lucia',
      filter: ['==', ['get', 'feature_type'], 'fire_cell'],
      layout: { visibility: vis('cata') },
      paint: {
        'fill-color': [
          'match',
          category,
          'BURNING_ACTIVE',
          CATA_COLORS.BURNING_ACTIVE[0],
          'ALREADY_BURNED',
          CATA_COLORS.ALREADY_BURNED[0],
          CATA_COLORS.THRESHOLD_BUFFER_UNSAFE[0],
        ],
        'fill-opacity': [
          'match',
          category,
          'BURNING_ACTIVE',
          CATA_COLORS.BURNING_ACTIVE[1],
          'ALREADY_BURNED',
          CATA_COLORS.ALREADY_BURNED[1],
          CATA_COLORS.THRESHOLD_BUFFER_UNSAFE[1],
        ],
        'fill-antialias': false,
      },
    });
  }
  if (!map.getLayer('be-ruta')) {
    map.addLayer({
      id: 'be-ruta',
      type: 'line',
      source: 'be-lucia',
      filter: ['==', ['get', 'feature_type'], 'evacuation_route'],
      layout: { visibility: vis('lucia'), 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': ['match', ['get', 'profile'], 'animal', LUCIA_ANIMAL, LUCIA_HUMAN],
        'line-width': ['interpolate', ['linear'], ['zoom'], 8, 2, 13, 5],
        // Personas en continuo; animales en discontinuo (se distinguen también sin color)
        'line-dasharray': [
          'match',
          ['get', 'profile'],
          'animal',
          ['literal', [2, 1.5]],
          ['literal', [1, 0]],
        ],
      },
    });
  }
  if (!map.getLayer('be-puntos')) {
    map.addLayer({
      id: 'be-puntos',
      type: 'circle',
      source: 'be-lucia',
      filter: ['in', ['get', 'feature_type'], ['literal', ['meeting_point', 'evacuation_origin']]],
      layout: { visibility: vis('lucia') },
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 4, 13, 8],
        'circle-color': [
          'match',
          ['get', 'feature_type'],
          'meeting_point',
          MEETING_COLOR,
          ORIGIN_COLOR,
        ],
        'circle-stroke-color': '#0b1020',
        'circle-stroke-width': 2,
      },
    });
  }
  if (!map.getLayer('be-juli-linea')) {
    map.addLayer({
      id: 'be-juli-linea',
      type: 'line',
      source: 'be-juli',
      filter: ['==', ['get', 'feature_type'], 'field_team_formation'],
      layout: { visibility: vis('juli') },
      paint: {
        'line-color': ['coalesce', ['get', 'stroke_color'], '#06b6d4'],
        'line-width': 2,
        'line-opacity': 0.75,
        'line-dasharray': [2, 2],
      },
    });
  }
  if (!map.getLayer('be-juli')) {
    const status: ExpressionSpecification = ['get', 'status'];
    map.addLayer({
      id: 'be-juli',
      type: 'circle',
      source: 'be-juli',
      filter: ['==', ['get', 'feature_type'], 'field_operator'],
      layout: { visibility: vis('juli') },
      paint: {
        'circle-radius': ['case', ['get', 'alerta'], 9, 6],
        'circle-color': [
          'match',
          status,
          ...Object.entries(JULI_STATUS).flatMap(([s, [c]]) => [s, c]),
          '#6b7280',
        ] as unknown as string,
        // Prueba de vida sin responder: aro rojo grueso (se ve también en gris)
        'circle-stroke-color': ['case', ['get', 'alerta'], '#ef4444', '#ffffff'],
        'circle-stroke-width': ['case', ['get', 'alerta'], 4, 2],
      },
    });
  }
}

const fmt = (n: unknown, digits = 0) =>
  typeof n === 'number' ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';

/**
 * Filas de la ficha de una feature del backend: [etiqueta, valor]. Las etiquetas pasan por t().
 */
export function backendDetails(props: Props): { title: string; rows: [string, string][] } {
  switch (props.feature_type) {
    case 'field_operator': {
      const status = JULI_STATUS[String(props.status)]?.[1] ?? String(props.status ?? '—');
      return {
        title: `${String(props.callsign ?? '')} · ${String(props.name ?? '')}`,
        rows: [
          ['Equipo', String(props.team_name ?? '—')],
          ['Función', String(props.role_label ?? props.role ?? '—')],
          ['Estado', status],
          ['Canal de radio', String(props.radio_channel ?? '—')],
          ['Cuadrante', String(props.quadrant_id ?? '—')],
          ...(props.alerta ? ([['Prueba de vida', 'Sin respuesta']] as [string, string][]) : []),
        ],
      };
    }
    case 'evacuation_route':
      return {
        title: String(props.profile_label ?? 'Ruta'),
        rows: [
          ['Destino', String(props.target_meeting_point_name ?? '—')],
          ['Distancia', `${fmt(props.distance_km, 1)} km`],
          ['Tiempo estimado', `${fmt(props.estimated_time_minutes)} min`],
          [
            'Probabilidad máx. de fuego en la ruta',
            `${fmt(Number(props.max_fire_probability_on_route) * 100)} %`,
          ],
        ],
      };
    case 'meeting_point':
      return {
        title: String(props.name ?? 'Punto de encuentro'),
        rows: [
          ['Capacidad', `${fmt(props.capacity)}`],
          ['Altitud', `${fmt(props.elevation_m)} m`],
          ['Distancia al fuego', `${fmt(props.distance_to_fire_km, 1)} km`],
        ],
      };
    case 'evacuation_origin':
      return {
        title: 'Punto de inicio en riesgo',
        rows: [
          ['Probabilidad de fuego', `${fmt(Number(props.fire_probability_t1) * 100)} %`],
          ['Distancia al fuego', `${fmt(props.distance_to_fire_km, 1)} km`],
        ],
      };
    default:
      return {
        title: 'Celda de CATA (1 km)',
        rows: [
          ['Categoría', CATEGORY_LABEL[String(props.fire_zone_category) as FireCategory] ?? '—'],
          ['Probabilidad de fuego', `${fmt(Number(props.fire_probability_t1) * 100)} %`],
          ['Predicción para', String(props.predicted_date ?? '—')],
        ],
      };
  }
}

export const CATEGORY_LABEL: Record<FireCategory, string> = {
  BURNING_ACTIVE: 'Ardiendo (predicción)',
  ALREADY_BURNED: 'Ya quemado',
  THRESHOLD_BUFFER_UNSAFE: 'Sin quemar, por encima del umbral seguro',
};
