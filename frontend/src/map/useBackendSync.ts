import { Popup, type Map as MapLibre, type MapGeoJSONFeature } from 'maplibre-gl';
import { useEffect, useRef, type RefObject } from 'react';
import { apiGet, wsUrl } from '../lib/api.ts';
import { t } from '../lib/i18n.ts';
import { useBackend } from '../store/backend.ts';
import { useUi } from '../store/ui.ts';
import {
  BACKEND_CLICKABLE,
  backendDetails,
  installBackendLayers,
  type JuliCollection,
  type LuciaCollection,
} from './backend.ts';

/** Respaldo de JULI si el WebSocket no llega (proxy, red móvil…) */
const JULI_POLL_MS = 20_000;
/** Reintento del WebSocket tras cortarse */
const WS_RETRY_MS = 5_000;

/** Ficha flotante de una feature del backend, con texto escapado (sin HTML del servidor). */
function popupContent(feature: MapGeoJSONFeature): HTMLElement {
  const { title, rows } = backendDetails(feature.properties as Record<string, unknown>);
  const root = document.createElement('div');
  root.className = 'flex flex-col gap-1 text-sm text-ink';
  const h = document.createElement('strong');
  h.textContent = t(title);
  root.append(h);
  const dl = document.createElement('dl');
  dl.className = 'm-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs';
  for (const [label, value] of rows) {
    const dt = document.createElement('dt');
    dt.className = 'text-ink-muted';
    dt.textContent = t(label);
    const dd = document.createElement('dd');
    dd.className = 'm-0';
    dd.textContent = t(value);
    dl.append(dt, dd);
  }
  const origin = document.createElement('p');
  origin.className = 'm-0 mt-1 text-xs font-semibold uppercase text-accent';
  origin.textContent = t('Backend · {m}', {
    m:
      feature.layer.id === 'be-juli'
        ? 'JULI'
        : feature.layer.id === 'be-cata-fill'
          ? 'CATA'
          : 'LUCIA',
  });
  root.append(dl, origin);
  return root;
}

/**
 * Conexión opcional con el backend (la salud la vigila useBackendHealth en el shell): descarga CATA + LUCIA y JULI, escucha
 * el WebSocket /ws para mover a los equipos en vivo y pinta todo en el mapa.
 */
export function useBackendSync(mapRef: RefObject<MapLibre | null>, ready: boolean) {
  const base = useBackend((s) => s.base);
  const status = useBackend((s) => s.status);
  const online = status === 'conectado';
  const lucia = useBackend((s) => s.lucia);
  const juli = useBackend((s) => s.juli);
  const layers = useUi((s) => s.layers);
  const live = useRef({ lucia, juli, layers });
  useEffect(() => {
    live.current = { lucia, juli, layers };
  });

  // Datos: CATA + LUCIA una vez (y al refrescar NRT); JULI con WebSocket y sondeo de respaldo
  useEffect(() => {
    if (!online) return;
    let alive = true;
    const store = useBackend.getState();
    const loadLucia = () =>
      apiGet<LuciaCollection>(base, '/api/lucia/routes', 30_000).then(
        (data) => alive && store.set({ lucia: data }),
        () => undefined,
      );
    const loadJuli = () =>
      apiGet<JuliCollection>(base, '/api/juli/geojson', 10_000).then(
        (data) => alive && store.set({ juli: data }),
        () => undefined,
      );
    void loadLucia();
    void loadJuli();
    const poll = window.setInterval(loadJuli, JULI_POLL_MS);

    let socket: WebSocket | undefined;
    let retry: number | undefined;
    let debounce: number | undefined;
    const connect = () => {
      try {
        socket = new WebSocket(wsUrl(base));
      } catch {
        return;
      }
      socket.onopen = () => alive && store.set({ socket: true });
      socket.onmessage = (message) => {
        let event = '';
        try {
          event = String((JSON.parse(String(message.data)) as { event?: unknown }).event ?? '');
        } catch {
          return;
        }
        if (event === 'live_nrt_updated') void loadLucia();
        if (event.startsWith('juli_') || event.startsWith('proof_of_life')) {
          // Varios eventos seguidos (un equipo entero se mueve): una sola descarga
          window.clearTimeout(debounce);
          debounce = window.setTimeout(loadJuli, 400);
        }
      };
      socket.onclose = () => {
        if (!alive) return;
        store.set({ socket: false });
        retry = window.setTimeout(connect, WS_RETRY_MS);
      };
    };
    connect();
    return () => {
      alive = false;
      window.clearInterval(poll);
      window.clearTimeout(retry);
      window.clearTimeout(debounce);
      socket?.close();
      useBackend.getState().set({ socket: false });
    };
  }, [online, base]);

  // Capas: con datos nuevos y tras cada cambio de mapa base (setStyle las borra)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    installBackendLayers(map, lucia, juli, layers);
    // `layers` solo se usa al crear las capas; después manda applyVisibility
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lucia, juli, ready, mapRef]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const reinstall = () => {
      const s = live.current;
      installBackendLayers(map, s.lucia, s.juli, s.layers);
    };
    map.on('style.load', reinstall);
    // Ficha al pulsar: equipos, rutas, puntos y celdas
    const popup = new Popup({ closeButton: true, maxWidth: '18rem', className: 'popup-backend' });
    const onClick = (e: {
      features?: MapGeoJSONFeature[];
      lngLat: { lng: number; lat: number };
    }) => {
      if (useUi.getState().mapTool) return;
      const feature = e.features?.[0];
      if (!feature) return;
      popup.setLngLat(e.lngLat).setDOMContent(popupContent(feature)).addTo(map);
    };
    const pointer = () => (map.getCanvas().style.cursor = 'pointer');
    const plain = () => (map.getCanvas().style.cursor = '');
    // Solo la capa de más arriba responde: los operarios tapan rutas y celdas
    const handlers = BACKEND_CLICKABLE.map((layer, i) => {
      const handler = (e: Parameters<typeof onClick>[0] & { point: { x: number; y: number } }) => {
        const above = BACKEND_CLICKABLE.slice(0, i).filter((l) => map.getLayer(l));
        if (
          above.length &&
          map.queryRenderedFeatures([e.point.x, e.point.y], { layers: above }).length
        )
          return;
        onClick(e);
      };
      map.on('click', layer, handler);
      map.on('mouseenter', layer, pointer);
      map.on('mouseleave', layer, plain);
      return [layer, handler] as const;
    });
    return () => {
      map.off('style.load', reinstall);
      for (const [layer, handler] of handlers) {
        map.off('click', layer, handler);
        map.off('mouseenter', layer, pointer);
        map.off('mouseleave', layer, plain);
      }
      popup.remove();
    };
  }, [ready, mapRef]);
}
