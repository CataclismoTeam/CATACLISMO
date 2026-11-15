import type { GeoJSONSource, LngLat, Map as MapLibre, MapMouseEvent } from 'maplibre-gl';
import { useEffect, type RefObject } from 'react';
import { useHistory } from '../store/history.ts';
import { useUi } from '../store/ui.ts';
import { AREA_COLOR } from './overlays.ts';

const SOURCE = 'dibujo-area';
/** Lado mínimo del área dibujada: una celda de 5 km de la rejilla del calendario */
const MIN_SIDE_DEG = 0.05;

function rectangle(a: LngLat, b: LngLat): GeoJSON.FeatureCollection {
  const [w, e] = [Math.min(a.lng, b.lng), Math.max(a.lng, b.lng)];
  const [s, n] = [Math.min(a.lat, b.lat), Math.max(a.lat, b.lat)];
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [w, s],
              [e, s],
              [e, n],
              [w, n],
              [w, s],
            ],
          ],
        },
      },
    ],
  };
}

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

function draft(map: MapLibre, data: GeoJSON.FeatureCollection) {
  const source = map.getSource(SOURCE) as GeoJSONSource | undefined;
  if (source) {
    source.setData(data);
    return;
  }
  map.addSource(SOURCE, { type: 'geojson', data });
  map.addLayer({
    id: 'dibujo-fill',
    type: 'fill',
    source: SOURCE,
    paint: { 'fill-color': AREA_COLOR, 'fill-opacity': 0.12 },
  });
  map.addLayer({
    id: 'dibujo-line',
    type: 'line',
    source: SOURCE,
    paint: { 'line-color': AREA_COLOR, 'line-width': 2 },
  });
}

/**
 * Herramienta «Dibujar área» del calendario: dos clics en el mapa forman un rectángulo que pasa a
 * ser el área de interés. Esc o el botón Cancelar la abandonan.
 */
export function useAreaDraw(map: RefObject<MapLibre | null>, ready: boolean) {
  const active = useUi((s) => s.mapTool === 'dibujar');

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !active) return;
    let first: LngLat | null = null;
    // El calendario se pliega para dejar sitio al mapa y vuelve a abrirse al terminar
    const calendarWasOpen = useUi.getState().calendarOpen;
    useUi.getState().setCalendarOpen(false);
    const canvas = m.getCanvas();
    canvas.style.cursor = 'crosshair';
    m.doubleClickZoom.disable();
    draft(m, EMPTY);

    const onClick = (e: MapMouseEvent) => {
      if (!first) {
        first = e.lngLat;
        draft(m, rectangle(first, first));
        return;
      }
      let [w, s, east, n] = [
        Math.min(first.lng, e.lngLat.lng),
        Math.min(first.lat, e.lngLat.lat),
        Math.max(first.lng, e.lngLat.lng),
        Math.max(first.lat, e.lngLat.lat),
      ];
      // Dos clics en el mismo sitio no forman un área: se espera a otra esquina
      if (east - w < 0.002 && n - s < 0.002) return;
      // Como mínimo una celda de la rejilla (5 km): si no, el calendario quedaría vacío
      const grow = (lo: number, hi: number): [number, number] => {
        const missing = MIN_SIDE_DEG - (hi - lo);
        return missing > 0 ? [lo - missing / 2, hi + missing / 2] : [lo, hi];
      };
      [w, east] = grow(w, east);
      [s, n] = grow(s, n);
      const round = (v: number) => Math.round(v * 1000) / 1000;
      useHistory.getState().setArea({
        kind: 'bbox',
        name: 'Área dibujada',
        west: round(w),
        south: round(s),
        east: round(east),
        north: round(n),
      });
      useUi.getState().setLayer('mes', true);
      useUi.getState().setMapTool(null);
    };
    const onMove = (e: MapMouseEvent) => {
      if (first) draft(m, rectangle(first, e.lngLat));
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') useUi.getState().setMapTool(null);
    };
    m.on('click', onClick);
    m.on('mousemove', onMove);
    window.addEventListener('keydown', onKey);
    return () => {
      m.off('click', onClick);
      m.off('mousemove', onMove);
      window.removeEventListener('keydown', onKey);
      canvas.style.cursor = '';
      m.doubleClickZoom.enable();
      if (m.getSource(SOURCE)) draft(m, EMPTY);
      if (calendarWasOpen) useUi.getState().setCalendarOpen(true);
    };
  }, [map, ready, active]);
}
