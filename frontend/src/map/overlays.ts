// Capas propias sobre el mapa base. Se reinstalan cada vez que cambia el estilo base
// (setStyle borra fuentes y capas), así que todo aquí es idempotente.
import type { FilterSpecification, GeoJSONSource, Map as MapLibre } from 'maplibre-gl';
import type { LayerId } from '../store/ui.ts';
import { Flame } from 'lucide';
import type { Detections } from './detections.ts';
import { fireCells } from './detections.ts';
import { incidentPoints, outlines, type IncidentsFile } from './incidents.ts';
import { provider } from './providers.ts';
import { NOW_H, routesGeoJson, spread, spreadFrom, type Route, type Scenario } from './scenario.ts';

// Predicción en tramas; el fuego (real o simulado) en celdas rojas sólidas.
/** Trama de cada franja: también cambia la forma, no solo el color (daltonismo, escala de grises). */
export type Pattern = '/' | '\\' | 'x';
export const PREDICTION_BANDS: [hours: number, color: string, label: string, pattern: Pattern][] = [
  [2, '#b5541e', '1–2 h', '/'],
  [4, '#c98a2b', '2–4 h', '\\'],
  [6, '#c9b46b', '4–6 h', 'x'],
];
export const ACTIVE_COLOR = '#c2331f';
/** Fuego real ya apagado (sin detecciones al cierre del dato): gris ceniza */
export const ASH_COLOR = '#6f6a66';
export const ROUTE_COLOR = '#2f9e62';
/** Halo ilustrativo de los incendios reales: gris neutro, nunca los colores del modelo */
export const HALO_COLOR = '#b8bcc4';

/** Color de un token CSS (cambia con el tema y el modo de daltonismo). */
export function tokenColor(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Capas de MapLibre que controla cada interruptor del panel. */
export const LAYER_IDS: Record<LayerId, string[]> = {
  detecciones: ['det-cell', 'real-fill', 'real-icon'],
  halo: ['halo-fill', 'halo-line'],
  mes: ['mes-fill', 'mes-line'],
  incendio: ['inc-fill'],
  prediccion: ['pred-tint', 'pred-fill'],
  unidades: [],
  evacuacion: ['ruta-casing', 'ruta-line', 'ruta-destacada'],
  curvas: ['curvas-line', 'curvas-label'],
  sombreado: ['sombreado'],
  // Backend: capas de map/backend.ts
  cata: ['be-cata-fill'],
  lucia: ['be-ruta', 'be-puntos'],
  juli: ['be-juli-linea', 'be-juli'],
};

/** Trama para la predicción: se distingue del fuego real también en gris. */
function hatch(
  color: string,
  pattern: Pattern,
): { width: number; height: number; data: Uint8ClampedArray } {
  const size = 24;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return { width: 1, height: 1, data: new Uint8ClampedArray(4) };
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (const o of [-size, 0, size]) {
    if (pattern !== '\\') {
      ctx.moveTo(o, size);
      ctx.lineTo(o + size, 0);
    }
    if (pattern !== '/') {
      ctx.moveTo(o, 0);
      ctx.lineTo(o + size, size);
    }
  }
  ctx.stroke();
  return { width: size, height: size, data: ctx.getImageData(0, 0, size, size).data };
}

function upsertSource(map: MapLibre, id: string, data: GeoJSON.FeatureCollection) {
  const source = map.getSource(id);
  if (source && 'setData' in source) (source as GeoJSONSource).setData(data);
  else map.addSource(id, { type: 'geojson', data });
}

/** Por debajo de este zoom se ve España entera: solo iconos, sin superficies ni rótulos. */
export const FAR_ZOOM = 9;
/** Capas del escenario simulado que solo tienen sentido de cerca */
const NEAR_ONLY = [
  'halo-fill',
  'halo-line',
  'pred-tint',
  'pred-fill',
  'inc-fill',
  'ruta-casing',
  'ruta-line',
];

type IconKind = 'ico-real-activo' | 'ico-real-inactivo' | 'ico-simulado';

/** Iconos de incendio dibujados en canvas: forma + llama, distinguibles sin color. */
function fireIcon(kind: IconKind) {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return { width: 1, height: 1, data: new Uint8ClampedArray(4) };
  const c = size / 2;
  ctx.lineWidth = 4;
  ctx.beginPath();
  if (kind === 'ico-simulado') {
    // Rombo: simulación
    ctx.moveTo(c, 3);
    ctx.lineTo(size - 3, c);
    ctx.lineTo(c, size - 3);
    ctx.lineTo(3, c);
    ctx.closePath();
    ctx.fillStyle = '#2a2110';
    ctx.strokeStyle = '#e0a640';
  } else {
    // Círculo: incendio real (relleno si sigue activo, anillo si no)
    ctx.arc(c, c, c - 4, 0, Math.PI * 2);
    ctx.fillStyle = kind === 'ico-real-activo' ? '#c2331f' : '#1d2026';
    ctx.strokeStyle = kind === 'ico-real-activo' ? '#fff1d6' : '#d9905a';
  }
  ctx.fill();
  ctx.stroke();
  // Llama de lucide (24×24) escalada al centro
  ctx.save();
  ctx.translate(c - 17, c - 18);
  ctx.scale(1.42, 1.42);
  ctx.strokeStyle = kind === 'ico-simulado' ? '#f2c14e' : '#fff6e6';
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  for (const [, attrs] of Flame) {
    if ('d' in attrs && typeof attrs.d === 'string') ctx.stroke(new Path2D(attrs.d));
  }
  ctx.restore();
  return { width: size, height: size, data: ctx.getImageData(0, 0, size, size).data };
}

function installIcons(map: MapLibre) {
  for (const kind of ['ico-real-activo', 'ico-real-inactivo', 'ico-simulado'] as IconKind[]) {
    if (!map.hasImage(kind)) map.addImage(kind, fireIcon(kind), { pixelRatio: 2 });
  }
}

function simulationPoints(list: Scenario[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: list.map((s) => ({
      type: 'Feature',
      properties: { id: s.id, nombre: s.name },
      geometry: { type: 'Point', coordinates: s.ignition },
    })),
  };
}

const firstSymbol = (map: MapLibre) => map.getStyle().layers.find((l) => l.type === 'symbol')?.id;

export function installOverlays(
  map: MapLibre,
  scenario: Scenario,
  routes: Route[],
  simulations: Scenario[],
  detections: Detections | undefined,
  incidents: IncidentsFile | undefined,
  visible: Record<LayerId, boolean>,
) {
  // Relieve: una fuente para el terreno 3D y otra para el sombreado (recomendación de MapLibre)
  if (!map.getSource('dem')) map.addSource('dem', provider.dem);
  if (!map.getSource('dem-sombra')) map.addSource('dem-sombra', provider.dem);
  const beforeLabels = firstSymbol(map);

  if (!map.getLayer('sombreado')) {
    map.addLayer(
      {
        id: 'sombreado',
        type: 'hillshade',
        source: 'dem-sombra',
        paint: { 'hillshade-exaggeration': 0.45, 'hillshade-shadow-color': '#1b1f24' },
      },
      beforeLabels,
    );
  }

  if (provider.contours && !map.getSource('curvas')) {
    map.addSource('curvas', { type: 'vector', url: provider.contours });
    const major: FilterSpecification = ['>=', ['get', 'nth_line'], 5];
    map.addLayer(
      {
        id: 'curvas-line',
        type: 'line',
        source: 'curvas',
        'source-layer': 'contour',
        paint: {
          'line-color': '#7a5a3a',
          'line-opacity': 0.85,
          'line-width': ['case', major, 1.4, 0.6],
        },
      },
      beforeLabels,
    );
    if (map.getStyle().glyphs) {
      map.addLayer({
        id: 'curvas-label',
        type: 'symbol',
        source: 'curvas',
        'source-layer': 'contour',
        filter: major,
        layout: {
          'symbol-placement': 'line',
          'text-field': ['concat', ['to-string', ['get', 'height']], ' m'],
          'text-size': 12,
          'text-font': ['Noto Sans Regular'],
        },
        paint: { 'text-color': '#4a3520', 'text-halo-color': '#f4efe6', 'text-halo-width': 1.5 },
      });
    }
  }

  for (const [hours, color, , pattern] of PREDICTION_BANDS) {
    const id = `trama-${hours}`;
    if (!map.hasImage(id)) map.addImage(id, hatch(color, pattern));
  }

  // Predicción (MODELO): celdas de 250 m con trama y borde discontinuo
  upsertSource(map, 'incendio', spread(scenario));

  // Halo ILUSTRATIVO de los incendios reales activos: FIRMS no trae viento, así que usa un
  // poniente fijo de ejemplo. Capa propia, gris y sin trama, para no confundirlo con el modelo.
  if (incidents) {
    const halo: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
    // Solo los activos: un halo por cada uno de los 232 pesaría demasiado y los antiguos ya no avanzan
    for (const i of incidents.incendios.filter((x) => x.activo)) {
      for (const f of spreadFrom([i.lon, i.lat], 270, 15).features) {
        if (f.properties.fase === 'prediccion') halo.features.push(f);
      }
    }
    upsertSource(map, 'halo-real', halo);
    if (!map.getLayer('halo-fill')) {
      map.addLayer(
        {
          id: 'halo-fill',
          type: 'fill',
          source: 'halo-real',
          paint: { 'fill-color': HALO_COLOR, 'fill-opacity': 0.22, 'fill-antialias': false },
        },
        beforeLabels,
      );
      map.addLayer(
        {
          id: 'halo-line',
          type: 'line',
          source: 'halo-real',
          paint: { 'line-color': HALO_COLOR, 'line-width': 0.4, 'line-opacity': 0.3 },
        },
        beforeLabels,
      );
    }
  }
  if (!map.getLayer('pred-fill')) {
    // Tinte translúcido por franja horaria + trama encima: se lee de lejos y en gris
    map.addLayer(
      {
        id: 'pred-tint',
        type: 'fill',
        source: 'incendio',
        filter: predictionFilter(NOW_H),
        paint: {
          'fill-color': [
            'step',
            ['get', 'horas'],
            PREDICTION_BANDS[0][1],
            2,
            PREDICTION_BANDS[1][1],
            4,
            PREDICTION_BANDS[2][1],
          ],
          'fill-opacity': 0.28,
          'fill-antialias': false,
        },
      },
      beforeLabels,
    );
    map.addLayer(
      {
        id: 'pred-fill',
        type: 'fill',
        source: 'incendio',
        filter: predictionFilter(NOW_H),
        paint: {
          'fill-opacity': 0.85,
          'fill-pattern': ['step', ['get', 'horas'], 'trama-2', 2, 'trama-4', 4, 'trama-6'],
          'fill-antialias': false,
        },
      },
      beforeLabels,
    );
    // Incendio activo (SIMULADO): celdas sólidas de 250 m, como en la referencia del equipo
    map.addLayer(
      {
        id: 'inc-fill',
        type: 'fill',
        source: 'incendio',
        filter: burntFilter(NOW_H),
        // Sin antialias: las celdas vecinas se funden en una mancha, sin costuras de rejilla
        paint: { 'fill-color': ACTIVE_COLOR, 'fill-opacity': 0.85, 'fill-antialias': false },
      },
      beforeLabels,
    );
  }

  // Incendios REALES (FIRMS): mismas celdas rojas de 250 m que el simulado. Con zoom lejano, un icono por incendio.
  if (detections) {
    upsertSource(map, 'celdas-reales', fireCells(detections));
    if (!map.getLayer('det-cell')) {
      map.addLayer(
        {
          id: 'det-cell',
          type: 'fill',
          source: 'celdas-reales',
          minzoom: FAR_ZOOM,
          paint: {
            'fill-color': ['case', ['get', 'activo'], ACTIVE_COLOR, ASH_COLOR],
            'fill-opacity': ['case', ['get', 'activo'], 0.85, 0.7],
            'fill-antialias': false,
          },
        },
        beforeLabels,
      );
    }
  }
  if (incidents) {
    upsertSource(map, 'incendios-reales', outlines(incidents));
    upsertSource(map, 'incendios-puntos', incidentPoints(incidents));
    if (!map.getLayer('real-line')) {
      map.addLayer(
        {
          id: 'real-fill',
          type: 'fill',
          source: 'incendios-reales',
          minzoom: FAR_ZOOM,
          // Casi transparente: solo sirve para pulsar el incendio y ver su ficha
          paint: { 'fill-color': '#000000', 'fill-opacity': 0.01 },
        },
        beforeLabels,
      );
    }
  }

  // Vista lejana: un icono por incendio (reales y simulaciones). Los que se solapan se ocultan
  // y quedan los de más actividad, para que el mapa no se llene de iconos.
  installIcons(map);
  if (incidents && !map.getLayer('real-icon')) {
    map.addLayer({
      id: 'real-icon',
      type: 'symbol',
      source: 'incendios-puntos',
      maxzoom: FAR_ZOOM,
      layout: {
        'icon-image': ['case', ['get', 'activo'], 'ico-real-activo', 'ico-real-inactivo'],
        'icon-size': ['interpolate', ['linear'], ['get', 'frpTotal'], 0, 0.55, 5000, 0.8, 50000, 1],
        'symbol-sort-key': ['-', 0, ['get', 'frpTotal']],
        'icon-allow-overlap': false,
        'icon-padding': 2,
      },
    });
  }
  upsertSource(map, 'simulaciones', simulationPoints(simulations));
  if (!map.getLayer('sim-icon')) {
    map.addLayer({
      id: 'sim-icon',
      type: 'symbol',
      source: 'simulaciones',
      maxzoom: FAR_ZOOM,
      layout: { 'icon-image': 'ico-simulado', 'icon-size': 0.85, 'icon-allow-overlap': true },
    });
  }

  // Vías de escape (SIMULADO)
  upsertSource(map, 'rutas', routesGeoJson(routes));
  if (!map.getLayer('ruta-line')) {
    map.addLayer({
      id: 'ruta-casing',
      type: 'line',
      source: 'rutas',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#0d1a12',
        'line-opacity': 0.85,
        // Más fina de lejos y más ancha de cerca: sin churretón negro sobre el relieve
        'line-width': ['interpolate', ['linear'], ['zoom'], 9, 3, 13, 6, 16, 10],
      },
    });
    map.addLayer({
      id: 'ruta-line',
      type: 'line',
      source: 'rutas',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': tokenColor('--color-route', ROUTE_COLOR),
        'line-width': ['interpolate', ['linear'], ['zoom'], 9, 1.5, 13, 3.5, 16, 6],
      },
    });
    // Ruta del aviso elegido: encima, más ancha y clara (se elige con applyHighlight)
    map.addLayer({
      id: 'ruta-destacada',
      type: 'line',
      source: 'rutas',
      filter: ['==', ['get', 'nombre'], ''],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#f4fbff',
        'line-width': ['interpolate', ['linear'], ['zoom'], 9, 3, 13, 6, 16, 9],
        'line-opacity': 0.95,
      },
    });
  }

  for (const id of NEAR_ONLY) if (map.getLayer(id)) map.setLayerZoomRange(id, FAR_ZOOM, 24);
  applyVisibility(map, visible);
}

// Línea de tiempo: lo que llega antes de la hora elegida ya ha ardido (rojo sólido); lo posterior
// es la predicción. El dato ('horas' de cada celda) no cambia: solo los filtros.
const burntFilter = (h: number): FilterSpecification => ['<=', ['get', 'horas'], h];
const predictionFilter = (h: number): FilterSpecification => ['>', ['get', 'horas'], h];

/** Muestra el incendio simulado a la hora `h` desde la ignición (0–6 h). */
export function applyFireHour(map: MapLibre, h: number) {
  for (const id of ['inc-fill']) if (map.getLayer(id)) map.setFilter(id, burntFilter(h));
  for (const id of ['pred-tint', 'pred-fill']) {
    if (map.getLayer(id)) map.setFilter(id, predictionFilter(h));
  }
}

/** Rampa de la rejilla mensual (detecciones equivalentes MODIS por celda de 5 km y mes). */
export const MONTH_RAMP: [value: number, color: string][] = [
  [1, '#2c3e8f'],
  [5, '#3f7fbf'],
  [25, '#58b0a0'],
  [100, '#d9c348'],
  [400, '#fde725'],
];
export const AREA_COLOR = '#7cc4ff';

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

/**
 * Capas del calendario (REAL): la rejilla de 5 km del mes elegido, bajo el fuego, y el contorno
 * del área de interés, encima. Idempotente: se llama al cargar el estilo y al cambiar los datos.
 */
export function installCalendarLayers(
  map: MapLibre,
  month: GeoJSON.FeatureCollection | undefined,
  area: GeoJSON.FeatureCollection | undefined,
  visible: Record<LayerId, boolean>,
) {
  upsertSource(map, 'mes-celdas', month ?? EMPTY);
  if (!map.getLayer('mes-fill')) {
    const below = ['halo-fill', 'pred-tint', 'det-cell'].find((id) => map.getLayer(id));
    const ramp = MONTH_RAMP.flatMap(([v, c]) => [Math.log(v), c]);
    map.addLayer(
      {
        id: 'mes-fill',
        type: 'fill',
        source: 'mes-celdas',
        paint: {
          'fill-color': [
            'interpolate',
            ['linear'],
            ['ln', ['max', 1, ['get', 'h']]],
            ...ramp,
          ] as unknown as string,
          'fill-opacity': 0.6,
        },
      },
      below,
    );
    map.addLayer(
      {
        id: 'mes-line',
        type: 'line',
        source: 'mes-celdas',
        minzoom: 7,
        paint: { 'line-color': '#0b1020', 'line-width': 0.4, 'line-opacity': 0.5 },
      },
      below,
    );
  }
  upsertSource(map, 'area-calendario', area ?? EMPTY);
  if (!map.getLayer('area-line')) {
    map.addLayer({
      id: 'area-line',
      type: 'line',
      source: 'area-calendario',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': AREA_COLOR, 'line-width': 2.5, 'line-dasharray': [3, 2] },
    });
  }
  applyVisibility(map, visible);
}

/** Resalta una vía de escape por su nombre (o ninguna). */
export function applyHighlight(map: MapLibre, route: string | undefined) {
  if (map.getLayer('ruta-destacada')) {
    map.setFilter('ruta-destacada', ['==', ['get', 'nombre'], route ?? '']);
  }
}

export function applyVisibility(map: MapLibre, visible: Record<LayerId, boolean>) {
  for (const [id, layers] of Object.entries(LAYER_IDS) as [LayerId, string[]][]) {
    for (const layer of layers) {
      if (map.getLayer(layer)) {
        map.setLayoutProperty(layer, 'visibility', visible[id] ? 'visible' : 'none');
      }
    }
  }
}
