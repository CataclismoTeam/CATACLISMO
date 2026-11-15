import 'maplibre-gl/dist/maplibre-gl.css';
import {
  Map as MapLibre,
  Marker,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
} from 'maplibre-gl';
// MapLibre 6 carga su worker como fichero aparte: Vite lo publica y aquí se le dice dónde está
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { useEffect, useRef, useState } from 'react';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';
import { loadDetections } from './detections.ts';
import { LayersPanel } from './LayersPanel.tsx';
import { declutterUnits, ignitionElement, meetingElement, unitElement } from './markers.ts';
import { IncidentsPanel } from './IncidentsPanel.tsx';
import { loadIncidents } from './incidents.ts';
import { applyVisibility, FAR_ZOOM, installOverlays, ROUTE_COLOR, tokenColor } from './overlays.ts';
import { provider } from './providers.ts';
import { DEFAULT_SCENARIO, loadEscapeRoutes, SCENARIOS, type Route } from './scenario.ts';
import { UnitsPanel } from './UnitsPanel.tsx';
import { ready as readyData, useRemote } from './useRemote.ts';
import {
  CoordinatesBar,
  FireCard,
  IncidentCard,
  UnitCard,
  type FireObservation,
} from './MapHud.tsx';

setWorkerUrl(workerUrl);

const PITCH_3D = 60;
/** A partir de este zoom las placas de las unidades muestran indicativo y estado */
const LABEL_ZOOM = 13;
const SIMULATIONS = Object.values(SCENARIOS);
const NO_ROUTES: Route[] = [];

/** Mapa de mando: un único MapLibre que cambia de estilo, relieve y cámara sin recrearse. */
export default function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibre | null>(null);
  const markers = useRef<Marker[]>([]);
  const [ready, setReady] = useState(false);
  const detectionsLoad = useRemote(loadDetections);
  const detections = readyData(detectionsLoad);
  const [selectedFire, setSelectedFire] = useState<FireObservation>();
  const [tileError, setTileError] = useState(false);
  const incidentsLoad = useRemote(loadIncidents);
  const incidents = readyData(incidentsLoad);
  const [far, setFar] = useState(false);
  const [mid, setMid] = useState(false);
  const selectedIncidentId = useUi((s) => s.selectedIncident);
  const focusIncident = useUi((s) => s.focusIncident);
  const flyTarget = useUi((s) => s.flyTarget);
  const leftOpen = useUi((s) => s.leftPanel !== null);
  const selectedIncident = incidents?.incendios.find((i) => i.id === selectedIncidentId);

  const mode = useUi((s) => s.mapMode);
  const exaggeration = useUi((s) => s.exaggeration);
  const basemap = useUi((s) => s.basemap);
  const scenarioId = useUi((s) => s.scenario);
  const layers = useUi((s) => s.layers);
  const scenario = SCENARIOS[scenarioId] ?? SCENARIOS[DEFAULT_SCENARIO];
  const selectedUnitId = useUi((s) => s.selectedUnit);
  const selected = scenario.units.find((u) => u.id === selectedUnitId);
  const escapeLoad = useRemote(loadEscapeRoutes);
  const escape = readyData(escapeLoad);
  const routes = escape?.escenarios[scenario.id]?.rutas ?? NO_ROUTES;

  // Estado vivo para los manejadores de MapLibre (se registran una sola vez)
  const live = useRef({
    scenario,
    routes,
    simulations: SIMULATIONS,
    detections,
    incidents,
    layers,
    mode,
    exaggeration,
  });
  useEffect(() => {
    live.current = {
      scenario,
      routes,
      simulations: SIMULATIONS,
      detections,
      incidents,
      layers,
      mode,
      exaggeration,
    };
  });

  useEffect(() => {
    if (!container.current) return;
    const { camera } = live.current.scenario;
    const map = new MapLibre({
      container: container.current,
      style: provider.style(useUi.getState().basemap),
      center: camera.center,
      zoom: camera.zoom,
      bearing: live.current.mode === '3d' ? camera.bearing : 0,
      pitch: live.current.mode === '3d' ? camera.pitch : 0,
      maxPitch: 80,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ visualizePitch: true }), 'top-right');
    // Abajo a la derecha: la esquina izquierda es para las fichas y las coordenadas (en móvil no
    // se muestran: no hay cursor y el centro del mapa ya se ve)
    map.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-right');

    map.on('style.load', () => {
      const s = live.current;
      installOverlays(
        map,
        s.scenario,
        s.routes,
        s.simulations,
        s.detections,
        s.incidents,
        s.layers,
      );
      map.setTerrain(s.mode === '3d' ? { source: 'dem', exaggeration: s.exaggeration } : null);
      setReady(true);
    });
    // Los manejadores por capa sobreviven a setStyle: se registran una vez, fuera de 'style.load'
    map.on('click', 'inc-fill', (event) => {
      const feature = event.features?.[0];
      const properties = feature?.properties as
        { intensidad?: number; altura?: number; horas?: number } | undefined;
      if (!feature || !properties) return;
      const point = event.lngLat;
      setSelectedFire({
        lon: point.lng,
        lat: point.lat,
        intensity: Number(properties.intensidad ?? 0),
        flameHeight: Number(properties.altura ?? 0),
        arrivalHours: Number(properties.horas ?? 0),
      });
      useUi.getState().focusUnit(undefined);
    });
    map.on('error', (e) => {
      // Una tesela que falla no rompe el mapa: se avisa y se sigue
      if ((e as { sourceId?: string }).sourceId) setTileError(true);
    });
    map.on('click', (event) => {
      const hits = map.queryRenderedFeatures(event.point, {
        layers: ['inc-fill', 'real-fill', 'real-icon', 'sim-icon'].filter((l) => map.getLayer(l)),
      });
      if (!hits.length) {
        useUi.getState().focusIncident(undefined);
        useUi.getState().focusUnit(undefined);
        setSelectedFire(undefined);
      }
    });

    // Vista lejana: fuera rótulos y marcadores, solo un icono por incendio
    const onZoom = () => {
      const z = map.getZoom();
      setFar(z < FAR_ZOOM);
      // Zoom medio: placas compactas (solo icono y estado) para que no se amontonen
      setMid(z >= FAR_ZOOM && z < LABEL_ZOOM);
    };
    map.on('zoom', onZoom);
    onZoom();
    map.on('click', 'real-fill', (e) => {
      const id = e.features?.[0]?.properties?.id;
      if (typeof id === 'string') useUi.getState().focusIncident(id);
    });
    // Pulsar un icono lejano acerca el mapa a ese incendio
    for (const layer of ['real-icon', 'sim-icon']) {
      map.on('click', layer, (e) => {
        const feature = e.features?.[0];
        if (!feature || feature.geometry.type !== 'Point') return;
        const id = feature.properties?.id;
        if (layer === 'real-icon' && typeof id === 'string') useUi.getState().focusIncident(id);
        if (layer === 'sim-icon' && typeof id === 'string') {
          useUi.getState().setScenario(id);
        }
        map.flyTo({ center: feature.geometry.coordinates as [number, number], zoom: 11.5 });
      });
      map.on('mouseenter', layer, () => (map.getCanvas().style.cursor = 'pointer'));
      map.on('mouseleave', layer, () => (map.getCanvas().style.cursor = ''));
    }

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Cambio de mapa base: setStyle borra las capas propias y 'style.load' las reinstala
  const firstStyle = useRef(true);
  useEffect(() => {
    if (firstStyle.current) {
      firstStyle.current = false;
      return;
    }
    mapRef.current?.setStyle(provider.style(basemap));
  }, [basemap]);

  // 2D: cenital, sin relieve ni rotación. 3D: relieve con inclinación libre (incluye la vista 2.5D)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (mode === '2d') {
      map.setTerrain(null);
      map.dragRotate.disable();
      map.touchZoomRotate.disableRotation();
      map.easeTo({ pitch: 0, bearing: 0, duration: 500 });
      map.setMaxPitch(0);
    } else {
      map.setMaxPitch(80);
      map.dragRotate.enable();
      map.touchZoomRotate.enableRotation();
      map.setTerrain({ source: 'dem', exaggeration: live.current.exaggeration });
      if (map.getPitch() < 10) map.easeTo({ pitch: PITCH_3D, duration: 500 });
    }
  }, [mode, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && ready && mode === '3d') map.setTerrain({ source: 'dem', exaggeration });
  }, [exaggeration, mode, ready]);

  useEffect(() => {
    if (mapRef.current && ready) applyVisibility(mapRef.current, layers);
  }, [layers, ready]);

  // Escenario o detecciones nuevas: datos de las capas, marcadores y encuadre
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    installOverlays(map, scenario, routes, SIMULATIONS, detections, incidents, live.current.layers);
  }, [scenario, routes, detections, incidents, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const { camera } = scenario;
    map.flyTo({
      center: camera.center,
      zoom: camera.zoom,
      bearing: live.current.mode === '3d' ? camera.bearing : 0,
      pitch: live.current.mode === '3d' ? camera.pitch : 0,
      duration: 1200,
    });
    useUi.getState().focusUnit(undefined);
  }, [scenario]);

  // Tema o daltonismo: las rutas toman el color del token (los marcadores ya usan variables CSS)
  const cvd = useUi((s) => s.cvd);
  const theme = useUi((s) => s.theme);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getLayer('ruta-line')) return;
    // Espera a que el shell aplique los atributos del tema al documento
    requestAnimationFrame(() =>
      map.setPaintProperty('ruta-line', 'line-color', tokenColor('--color-route', ROUTE_COLOR)),
    );
  }, [cvd, theme, ready]);

  // Esc cierra cualquier ficha abierta
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      useUi.getState().focusUnit(undefined);
      setSelectedFire(undefined);
      useUi.getState().focusIncident(undefined);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Encuadre pedido desde la lista de incendios
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !flyTarget) return;
    const [w, s, e, n] = flyTarget.bbox;
    map.fitBounds(
      [
        [w, s],
        [e, n],
      ],
      { padding: 80, maxZoom: 13, duration: 1200 },
    );
  }, [flyTarget]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const m of markers.current) m.remove();
    markers.current = [];
    const add = (
      el: HTMLElement,
      lngLat: [number, number],
      anchor: 'center' | 'bottom' = 'center',
    ) => markers.current.push(new Marker({ element: el, anchor }).setLngLat(lngLat).addTo(map));
    if (layers.unidades) {
      for (const unit of scenario.units)
        add(
          unitElement(unit, (u) => useUi.getState().focusUnit(u.id)),
          [unit.lon, unit.lat],
        );
    }
    if (layers.evacuacion) {
      for (const route of routes) {
        add(
          meetingElement(`Refugio ${route.refugio}`),
          route.coords.at(-1) ?? route.coords[0],
          'bottom',
        );
      }
    }
    if (layers.incendio) add(ignitionElement(), scenario.ignition, 'bottom');
    // Las placas que se pisan se reducen a icono; depende del zoom, así que se repite al mover
    const declutter = () => declutterUnits(markers.current.map((m) => m.getElement()));
    declutter();
    map.on('moveend', declutter);
    return () => {
      map.off('moveend', declutter);
    };
  }, [scenario, routes, layers.unidades, layers.evacuacion, layers.incendio]);

  return (
    <div className={cn('absolute inset-0', far && 'map-far', mid && 'map-mid')}>
      {/* Estilo en línea: la hoja de MapLibre (sin capa) pondría position: relative */}
      <div ref={container} style={{ position: 'absolute', inset: 0 }} data-testid="mapa" />
      {!ready && (
        <p role="status" className="map-placeholder absolute inset-0 m-0 grid place-items-center">
          <span className="rounded-sm bg-canvas px-3 py-1.5">Cargando el mapa…</span>
        </p>
      )}
      <IncidentsPanel
        incidents={incidentsLoad}
        routes={routes}
        routesRetry={escapeLoad.status === 'error' ? escapeLoad.retry : undefined}
      />
      <UnitsPanel />
      {/* Esquina superior derecha: capas y ficha del incendio se apilan, nunca se pisan.
          En móvil cada una va a su sitio (capas como hoja inferior). */}
      <div className="contents md:pointer-events-none md:absolute md:top-3 md:right-14 md:bottom-3 md:z-(--z-panel) md:flex md:flex-col md:items-end md:gap-2 md:*:pointer-events-auto">
        <LayersPanel detections={detectionsLoad} />
        {selectedIncident && (
          <IncidentCard
            incident={selectedIncident}
            dataEnd={incidents?.hasta}
            onClose={() => focusIncident(undefined)}
          />
        )}
      </div>
      {/* Esquina inferior izquierda: fichas y coordenadas, a la derecha del panel lateral */}
      <div
        className={cn(
          'pointer-events-none absolute top-3 bottom-3 left-3 flex max-w-[calc(100%-1.5rem)] flex-col items-start justify-end gap-2 *:pointer-events-auto',
          leftOpen && 'max-md:hidden md:left-[21.5rem] md:max-w-[calc(100%-22.25rem)]',
        )}
      >
        {selected && (
          <UnitCard unit={selected} onClose={() => useUi.getState().focusUnit(undefined)} />
        )}
        {selectedFire && (
          <FireCard observation={selectedFire} onClose={() => setSelectedFire(undefined)} />
        )}
        <CoordinatesBar map={mapRef} ready={ready} />
      </div>
      {tileError && (
        <p
          role="status"
          className="absolute top-3 left-1/2 m-0 -translate-x-1/2 rounded-md border border-warn bg-surface px-3 py-1.5 text-sm"
        >
          Parte del mapa no se ha podido descargar. Comprueba la conexión; el resto sigue
          funcionando.
        </p>
      )}
    </div>
  );
}
