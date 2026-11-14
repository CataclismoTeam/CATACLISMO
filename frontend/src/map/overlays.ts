// Capas propias sobre el mapa base. Se reinstalan cada vez que cambia el estilo base
// (setStyle borra fuentes y capas), así que todo aquí es idempotente.
import type { FilterSpecification, GeoJSONSource, Map as MapLibre } from 'maplibre-gl';
import type { LayerId } from '../store/ui.ts';
import type { Detections } from './detections.ts';
import { provider } from './providers.ts';
import { routesGeoJson, spread, type Scenario } from './scenario.ts';

// Rampas sobrias (sin neones): fuego real en tintas sólidas, predicción en tramas.
export const FRP_RAMP: [number, string][] = [
  [0, '#f2c14e'],
  [10, '#f08a3c'],
  [50, '#d9482b'],
  [200, '#8f1d1d'],
];
export const PREDICTION_BANDS: [hours: number, color: string, label: string][] = [
  [2, '#b5541e', '1–2 h'],
  [4, '#c98a2b', '2–4 h'],
  [6, '#c9b46b', '4–6 h'],
];
export const ACTIVE_COLOR = '#c2331f';
export const ROUTE_COLOR = '#2f9e62';

/** Capas de MapLibre que controla cada interruptor del panel. */
export const LAYER_IDS: Record<LayerId, string[]> = {
  detecciones: ['det-fill', 'det-line'],
  incendio: ['inc-fill', 'inc-line'],
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

const firstSymbol = (map: MapLibre) => map.getStyle().layers.find((l) => l.type === 'symbol')?.id;

export function installOverlays(
  map: MapLibre,
  scenario: Scenario,
  detections: Detections | undefined,
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
    // Incendio activo (SIMULADO): celdas sólidas
    map.addLayer(
      {
        id: 'inc-fill',
        type: 'fill',
        source: 'incendio',
        filter: ['==', ['get', 'fase'], 'activo'],
        paint: { 'fill-color': ACTIVE_COLOR, 'fill-opacity': 0.82 },
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

  // Detecciones REALES de FIRMS: huella del píxel, color por potencia radiativa (FRP)
  if (detections) {
    upsertSource(map, 'detecciones', detections.geojson);
    if (!map.getLayer('det-fill')) {
      map.addLayer({
        id: 'det-fill',
        type: 'fill',
        source: 'detecciones',
        paint: {
          'fill-color': ['interpolate', ['linear'], ['get', 'frp'], ...FRP_RAMP.flat()],
          'fill-opacity': 0.9,
        },
      });
      map.addLayer({
        id: 'det-line',
        type: 'line',
        source: 'detecciones',
        paint: { 'line-color': '#fff6e0', 'line-width': 1 },
      });
    }
  }

  // Vías de escape (SIMULADO)
  upsertSource(map, 'rutas', routesGeoJson(scenario));
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
      paint: { 'line-color': ROUTE_COLOR, 'line-width': 4.5 },
    });
  }

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
