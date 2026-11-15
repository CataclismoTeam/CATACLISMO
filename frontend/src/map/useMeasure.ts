import type { GeoJSONSource, Map as MapLibre, MapMouseEvent } from 'maplibre-gl';
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { useUi } from '../store/ui.ts';
import { areaKm2, lengthKm, type LonLat } from './measure.ts';

const SOURCE = 'medida';
const COLOR = '#ffe066';
/** Un clic a menos de estos píxeles del primer punto cierra el polígono */
const CLOSE_PX = 12;

function geojson(points: LonLat[], closed: boolean, cursor?: LonLat): GeoJSON.FeatureCollection {
  const line = cursor && !closed ? [...points, cursor] : points;
  const features: GeoJSON.Feature[] = points.map((p, i) => ({
    type: 'Feature',
    properties: { first: i === 0 },
    geometry: { type: 'Point', coordinates: p },
  }));
  if (closed) {
    features.push({
      type: 'Feature',
      properties: {},
      geometry: { type: 'Polygon', coordinates: [[...points, points[0]]] },
    });
  } else if (line.length > 1) {
    features.push({
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: line },
    });
  }
  return { type: 'FeatureCollection', features };
}

function draw(map: MapLibre, data: GeoJSON.FeatureCollection) {
  const source = map.getSource(SOURCE) as GeoJSONSource | undefined;
  if (source) {
    source.setData(data);
    return;
  }
  map.addSource(SOURCE, { type: 'geojson', data });
  map.addLayer({
    id: 'medida-fill',
    type: 'fill',
    source: SOURCE,
    filter: ['==', ['geometry-type'], 'Polygon'],
    paint: { 'fill-color': COLOR, 'fill-opacity': 0.15 },
  });
  map.addLayer({
    id: 'medida-line',
    type: 'line',
    source: SOURCE,
    filter: ['!=', ['geometry-type'], 'Point'],
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': COLOR, 'line-width': 2.5, 'line-dasharray': [2, 1] },
  });
  map.addLayer({
    id: 'medida-puntos',
    type: 'circle',
    source: SOURCE,
    filter: ['==', ['geometry-type'], 'Point'],
    paint: {
      'circle-radius': ['case', ['get', 'first'], 6, 4],
      'circle-color': COLOR,
      'circle-stroke-color': '#1b1f24',
      'circle-stroke-width': 1.5,
    },
  });
}

export interface Measurement {
  points: number;
  closed: boolean;
  km: number;
  km2: number;
  close: () => void;
  clear: () => void;
}

/**
 * Regla del mapa: cada clic añade un punto a la línea y se ve su longitud; al cerrarla (clic en el
 * primer punto o botón) se ve también la superficie. Esc la cancela.
 */
export function useMeasure(map: RefObject<MapLibre | null>, ready: boolean): Measurement | null {
  const active = useUi((s) => s.mapTool === 'medir');
  const [points, setPoints] = useState<LonLat[]>([]);
  const [closed, setClosed] = useState(false);
  const live = useRef({ points, closed });
  useEffect(() => {
    live.current = { points, closed };
  });

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !active) return;
    const canvas = m.getCanvas();
    canvas.style.cursor = 'crosshair';
    m.doubleClickZoom.disable();
    draw(m, geojson([], false));

    const onClick = (e: MapMouseEvent) => {
      const { points: pts, closed: done } = live.current;
      if (done) return;
      const p: LonLat = [e.lngLat.lng, e.lngLat.lat];
      if (pts.length >= 3) {
        const first = m.project(pts[0]);
        if (Math.hypot(first.x - e.point.x, first.y - e.point.y) < CLOSE_PX) {
          setClosed(true);
          return;
        }
      }
      setPoints([...pts, p]);
    };
    const onMove = (e: MapMouseEvent) => {
      const { points: pts, closed: done } = live.current;
      if (pts.length && !done) draw(m, geojson(pts, false, [e.lngLat.lng, e.lngLat.lat]));
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
      if (m.getSource(SOURCE)) draw(m, geojson([], false));
      setPoints([]);
      setClosed(false);
    };
  }, [map, ready, active]);

  // Cada cambio de puntos se pinta (el cursor solo se sigue con ratón)
  useEffect(() => {
    const m = map.current;
    if (m && ready && active) draw(m, geojson(points, closed));
  }, [map, ready, active, points, closed]);

  const close = useCallback(() => {
    if (live.current.points.length >= 3) setClosed(true);
  }, []);
  const clear = useCallback(() => {
    setPoints([]);
    setClosed(false);
  }, []);

  if (!active) return null;
  return {
    points: points.length,
    closed,
    km: lengthKm(points, closed),
    km2: closed ? areaKm2(points) : 0,
    close,
    clear,
  };
}
