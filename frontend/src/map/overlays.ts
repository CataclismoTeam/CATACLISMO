// Capas propias sobre el mapa base. Se reinstalan cada vez que cambia el estilo base
// (setStyle borra fuentes y capas), así que todo aquí es idempotente.
import type { FilterSpecification, GeoJSONSource, Map as MapLibre } from 'maplibre-gl';
import type { LayerId } from '../store/ui.ts';
import { Flame } from 'lucide';
import type { Detections } from './detections.ts';
import { incidentPoints, outlines, type IncidentsFile } from './incidents.ts';
import { provider } from './providers.ts';
import { routesGeoJson, spread, type Route, type Scenario } from './scenario.ts';

// Rampas sobrias (sin neones): fuego real en tintas sólidas, predicción en tramas.
export const FRP_RAMP: [number, string][] = [
  [0, '#f2c14e'],
  [10, '#f08a3c'],
  [50, '#d9482b'],
  [200, '#8f1d1d'],
];
export const FIRE_INTENSITY_RAMP: [number, string][] = [
  [0, '#fff3b0'],
  [500, '#ffd166'],
  [2000, '#f08a3c'],
  [5000, '#d9482b'],
  [8000, '#8f1d1d'],
];
export const PREDICTION_BANDS: [hours: number, color: string, label: string][] = [
  [2, '#b5541e', '1–2 h'],
  [4, '#c98a2b', '2–4 h'],
  [6, '#c9b46b', '4–6 h'],
];
export const ACTIVE_COLOR = '#c2331f';
export const ROUTE_COLOR = '#2f9e62';

/** Color de un token CSS (cambia con el tema y el modo de daltonismo). */
export function tokenColor(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Capas de MapLibre que controla cada interruptor del panel. */
export const LAYER_IDS: Record<LayerId, string[]> = {
  detecciones: ['det-heat', 'real-fill', 'real-line', 'real-icon'],
  incendio: ['inc-glow', 'inc-fill', 'inc-extrusion', 'inc-line'],
  prediccion: ['pred-tint', 'pred-fill', 'pred-line'],
  unidades: [],
  evacuacion: ['ruta-casing', 'ruta-line'],
  curvas: ['curvas-line', 'curvas-label'],
  sombreado: ['sombreado'],
};

/** Trama diagonal para la predicción: se distingue del fuego real también en gris. */
function hatch(color: string): { width: number; height: number; data: Uint8ClampedArray } {
  const size = 24;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return { width: 1, height: 1, data: new Uint8ClampedArray(4) };
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (const o of [-size, 0, size]) {
    ctx.moveTo(o, size);
    ctx.lineTo(o + size, 0);
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
  'pred-tint',
  'pred-fill',
  'pred-line',
  'inc-glow',
  'inc-fill',
  'inc-extrusion',
  'inc-line',
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

  for (const [hours, color] of PREDICTION_BANDS) {
    const id = `trama-${hours}`;
    if (!map.hasImage(id)) map.addImage(id, hatch(color));
  }

  // Predicción (MODELO): celdas de 250 m con trama y borde discontinuo
  const cells = spread(scenario);
  upsertSource(map, 'incendio', cells);
  if (!map.getLayer('pred-fill')) {
    // Tinte translúcido por franja horaria + trama encima: se lee de lejos y en gris
    map.addLayer(
      {
        id: 'pred-tint',
        type: 'fill',
        source: 'incendio',
        filter: ['==', ['get', 'fase'], 'prediccion'],
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
        filter: ['==', ['get', 'fase'], 'prediccion'],
        paint: {
          'fill-opacity': 0.85,
          'fill-pattern': ['step', ['get', 'horas'], 'trama-2', 2, 'trama-4', 4, 'trama-6'],
        },
      },
      beforeLabels,
    );
    map.addLayer(
      {
        id: 'pred-line',
        type: 'line',
        source: 'incendio',
        filter: ['==', ['get', 'fase'], 'prediccion'],
        paint: {
          'line-color': '#e0b070',
          'line-width': 0.4,
          'line-opacity': 0.35,
        },
      },
      beforeLabels,
    );
    // Incendio activo (SIMULADO): superficie térmica y altura de llama.
    map.addLayer(
      {
        id: 'inc-extrusion',
        type: 'fill-extrusion',
        source: 'incendio',
        filter: ['==', ['get', 'fase'], 'activo'],
        paint: {
          'fill-extrusion-color': [
            'interpolate',
            ['linear'],
            ['get', 'intensidad'],
            ...FIRE_INTENSITY_RAMP.flat(),
          ],
          'fill-extrusion-height': ['get', 'altura'],
          'fill-extrusion-base': 0,
          'fill-extrusion-opacity': 0.78,
          'fill-extrusion-vertical-gradient': true,
        },
      },
      beforeLabels,
    );
    map.addLayer(
      {
        id: 'inc-fill',
        type: 'fill',
        source: 'incendio',
        filter: ['==', ['get', 'fase'], 'activo'],
        paint: {
          'fill-color': [
            'interpolate',
            ['linear'],
            ['get', 'intensidad'],
            ...FIRE_INTENSITY_RAMP.flat(),
          ],
          'fill-opacity': 0.64,
          'fill-antialias': true,
        },
      },
      beforeLabels,
    );
    map.addLayer(
      {
        id: 'inc-glow',
        type: 'line',
        source: 'incendio',
        filter: ['==', ['get', 'fase'], 'activo'],
        paint: {
          'line-color': '#ffdf8a',
          'line-width': 3,
          'line-blur': 5,
          'line-opacity': 0.65,
        },
      },
      beforeLabels,
    );
    map.addLayer(
      {
        id: 'inc-line',
        type: 'line',
        source: 'incendio',
        filter: ['==', ['get', 'fase'], 'activo'],
        paint: { 'line-color': '#2a0d08', 'line-width': 0.5, 'line-opacity': 0.6 },
      },
      beforeLabels,
    );
  }

  // Incendios REALES (FIRMS): superficie de calor ponderada por FRP y contorno del área
  // afectada. Con zoom lejano se apagan y queda un único icono por incendio.
  if (detections) {
    upsertSource(map, 'detecciones', detections.geojson);
    if (!map.getLayer('det-heat')) {
      map.addLayer(
        {
          id: 'det-heat',
          type: 'heatmap',
          source: 'detecciones',
          minzoom: FAR_ZOOM - 1,
          paint: {
            'heatmap-weight': ['interpolate', ['linear'], ['get', 'frp'], 0, 0.15, 100, 1],
            'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 13, 2.2],
            'heatmap-radius': ['interpolate', ['exponential', 2], ['zoom'], 8, 6, 12, 22, 15, 70],
            'heatmap-color': [
              'interpolate',
              ['linear'],
              ['heatmap-density'],
              0,
              'rgba(0,0,0,0)',
              0.15,
              FIRE_INTENSITY_RAMP[0][1],
              0.35,
              FIRE_INTENSITY_RAMP[1][1],
              0.6,
              FIRE_INTENSITY_RAMP[2][1],
              0.8,
              FIRE_INTENSITY_RAMP[3][1],
              1,
              FIRE_INTENSITY_RAMP[4][1],
            ],
            'heatmap-opacity': [
              'interpolate',
              ['linear'],
              ['zoom'],
              FAR_ZOOM - 1,
              0,
              FAR_ZOOM,
              0.85,
            ],
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
      map.addLayer(
        {
          id: 'real-line',
          type: 'line',
          source: 'incendios-reales',
          minzoom: FAR_ZOOM,
          layout: { 'line-join': 'round' },
          paint: { 'line-color': '#fff1d6', 'line-width': 1.6, 'line-opacity': 0.9 },
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
      paint: { 'line-color': '#0d1a12', 'line-width': 8 },
    });
    map.addLayer({
      id: 'ruta-line',
      type: 'line',
      source: 'rutas',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': tokenColor('--color-route', ROUTE_COLOR), 'line-width': 4.5 },
    });
  }

  for (const id of NEAR_ONLY) if (map.getLayer(id)) map.setLayerZoomRange(id, FAR_ZOOM, 24);
  applyVisibility(map, visible);
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
