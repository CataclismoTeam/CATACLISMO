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
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { Check, X } from 'lucide-react';
import { areaRing, monthCells } from '../features/history/mapLayers.ts';
import { formatMonth } from '../lib/format.ts';
import { useHistory } from '../store/history.ts';
import { Button } from '../ui/Button.tsx';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';
import { loadDetections } from './detections.ts';
import { LayersPanel } from './LayersPanel.tsx';
import { declutterUnits, ignitionElement, meetingElement, unitElement } from './markers.ts';
import { IncidentsPanel } from './IncidentsPanel.tsx';
import { loadIncidents } from './incidents.ts';
import { alertsFor } from './alerts.ts';
import { AlertsPanel } from './AlertsPanel.tsx';
import { FireTimeline } from './FireTimeline.tsx';
import {
  applyFireHour,
  applyHighlight,
  applyVisibility,
  FAR_ZOOM,
  installCalendarLayers,
  installOverlays,
  ROUTE_COLOR,
  tokenColor,
} from './overlays.ts';
import { provider } from './providers.ts';
import { DEFAULT_SCENARIO, loadEscapeRoutes, SCENARIOS, type Route } from './scenario.ts';
import { UnitsPanel } from './UnitsPanel.tsx';
import { initialView } from '../lib/hash.ts';
import { useAreaDraw } from './useAreaDraw.ts';
import { useShareHash } from './useShareHash.ts';
import { MapToolbar } from './MapToolbar.tsx';
import { formatArea, formatLength } from './measure.ts';
import { SearchBox } from './SearchBox.tsx';
import { useMeasure } from './useMeasure.ts';
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

/** A partir de 1024 px el buscador va en la barra superior; por debajo, sobre el mapa. */
const WIDE = '(min-width: 1024px)';
const subscribeWide = (cb: () => void) => {
  const media = window.matchMedia(WIDE);
  media.addEventListener('change', cb);
  return () => media.removeEventListener('change', cb);
};
const isWide = () => window.matchMedia(WIDE).matches;

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
  /** El punto de ignición de la simulación activa está en pantalla */
  const [simInView, setSimInView] = useState(true);
  const fireHour = useUi((s) => s.fireHour);
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

  // Calendario → mapa: rejilla del mes elegido y contorno del área de interés (REAL)
  const grid = useHistory((s) => s.grid);
  const manifest = useHistory((s) => s.manifest);
  const month = useHistory((s) => s.selected);
  const area = useHistory((s) => s.area);
  const monthFc = useMemo(
    () =>
      layers.mes && grid && manifest
        ? monthCells(grid, manifest.rejilla, manifest.tiempo.anioInicial, month)
        : undefined,
    [layers.mes, grid, manifest, month],
  );
  const areaFc = useMemo((): GeoJSON.FeatureCollection | undefined => {
    const ring = areaRing(area);
    return ring
      ? {
          type: 'FeatureCollection',
          features: [
            { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } },
          ],
        }
      : undefined;
  }, [area]);
  const tool = useUi((s) => s.mapTool);

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
    monthFc,
    areaFc,
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
      monthFc,
      areaFc,
    };
  });

  useEffect(() => {
    if (!container.current) return;
    const { camera } = live.current.scenario;
    const map = new MapLibre({
      container: container.current,
      style: provider.style(useUi.getState().basemap),
      // Un enlace compartido abre con su encuadre; si no, el de la simulación
      center: initialView.center ?? camera.center,
      zoom: initialView.zoom ?? camera.zoom,
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
      installCalendarLayers(map, s.monthFc, s.areaFc, s.layers);
      applyFireHour(map, useUi.getState().fireHour);
      applyHighlight(map, useUi.getState().highlightRoute);
      map.setTerrain(s.mode === '3d' ? { source: 'dem', exaggeration: s.exaggeration } : null);
      setReady(true);
    });
    // Los manejadores por capa sobreviven a setStyle: se registran una vez, fuera de 'style.load'
    // Con una herramienta activa (dibujar, medir) los clics son para ella, no para seleccionar
    const busy = () => useUi.getState().mapTool !== null;
    map.on('click', 'inc-fill', (event) => {
      if (busy()) return;
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
      if (busy()) return;
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
    const onMoveEnd = () => setSimInView(map.getBounds().contains(live.current.scenario.ignition));
    map.on('moveend', onMoveEnd);
    map.on('click', 'real-fill', (e) => {
      if (busy()) return;
      const id = e.features?.[0]?.properties?.id;
      if (typeof id === 'string') useUi.getState().focusIncident(id);
    });
    // Pulsar un icono lejano acerca el mapa a ese incendio
    for (const layer of ['real-icon', 'sim-icon']) {
      map.on('click', layer, (e) => {
        if (busy()) return;
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
    applyFireHour(map, useUi.getState().fireHour);
    applyHighlight(map, useUi.getState().highlightRoute);
  }, [scenario, routes, detections, incidents, ready]);

  const highlightRoute = useUi((s) => s.highlightRoute);
  useEffect(() => {
    if (mapRef.current && ready) applyHighlight(mapRef.current, highlightRoute);
  }, [highlightRoute, ready]);

  // El botón del rail muestra cuántos avisos críticos tiene la simulación activa
  useEffect(() => {
    useUi
      .getState()
      .setCriticalAlerts(alertsFor(routes).filter((a) => a.level === 'critico').length);
  }, [routes]);

  useEffect(() => {
    if (mapRef.current && ready) applyFireHour(mapRef.current, fireHour);
  }, [fireHour, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && ready) installCalendarLayers(map, monthFc, areaFc, live.current.layers);
  }, [monthFc, areaFc, ready]);

  useAreaDraw(mapRef, ready);
  useShareHash(mapRef, ready);
  const measure = useMeasure(mapRef, ready);
  const wide = useSyncExternalStore(subscribeWide, isWide);
  const [searchOpen, setSearchOpen] = useState(false);
  const [copied, setCopied] = useState<boolean>();
  useEffect(() => {
    if (copied === undefined) return;
    const id = window.setTimeout(() => setCopied(undefined), 2500);
    return () => window.clearTimeout(id);
  }, [copied]);
  const searchSlot =
    typeof document === 'undefined' ? null : document.getElementById('buscador-barra');

  // Fuera de cuadro o de lejos no hay nada que animar: se pausa
  // Oculta también con una herramienta activa: dibujar o medir necesitan el mapa libre
  const showTimeline =
    ready && !far && simInView && !tool && (layers.incendio || layers.prediccion);
  useEffect(() => {
    if (!showTimeline) useUi.getState().setPlaying(false);
  }, [showTimeline]);

  // Con un encuadre compartido en el enlace, la primera vez no se vuela a la cámara del escenario
  const keepSharedCamera = useRef(!!initialView.center);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (keepSharedCamera.current) {
      keepSharedCamera.current = false;
      return;
    }
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

  // Encuadre pedido desde fuera del mapa (lista de incendios, área del calendario…)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !flyTarget) return;
    const [w, s, e, n] = flyTarget.bbox;
    const fit = (duration: number) => {
      const canvas = map.getCanvas();
      map.fitBounds(
        [
          [w, s],
          [e, n],
        ],
        {
          // Margen proporcional: con el calendario abierto el mapa puede medir solo 200 px de alto
          padding: Math.round(
            Math.min(80, 0.15 * Math.min(canvas.clientWidth, canvas.clientHeight)),
          ),
          maxZoom: 13,
          duration,
        },
      );
    };
    fit(1200);
    // Si el mapa cambia de tamaño justo después (se pliega o abre el calendario), se reencuadra
    const onResize = () => {
      if (Date.now() - flyTarget.at < 3000) fit(0);
    };
    map.on('resize', onResize);
    return () => {
      map.off('resize', onResize);
    };
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
    <div className={cn('absolute inset-0', far && 'map-far', mid && 'map-mid', tool && 'map-tool')}>
      {/* Estilo en línea: la hoja de MapLibre (sin capa) pondría position: relative */}
      <div ref={container} style={{ position: 'absolute', inset: 0 }} data-testid="mapa" />
      {!ready && (
        <p role="status" className="map-placeholder absolute inset-0 m-0 grid place-items-center">
          <span className="rounded-sm bg-canvas px-3 py-1.5">Cargando el mapa…</span>
        </p>
      )}
      {wide && searchSlot && createPortal(<SearchBox className="w-full max-w-sm" />, searchSlot)}
      <IncidentsPanel
        incidents={incidentsLoad}
        routes={routes}
        routesRetry={escapeLoad.status === 'error' ? escapeLoad.retry : undefined}
      />
      <UnitsPanel />
      <AlertsPanel
        routes={routes}
        nucleos={escape?.escenarios[scenario.id]?.nucleos}
        loading={escapeLoad.status === 'cargando'}
        retry={escapeLoad.status === 'error' ? escapeLoad.retry : undefined}
      />
      {/* Esquina superior derecha: capas y ficha del incendio se apilan, nunca se pisan.
          En móvil cada una va a su sitio (capas como hoja inferior). */}
      <div className="contents md:pointer-events-none md:absolute md:top-3 md:right-14 md:bottom-3 md:z-(--z-panel) md:flex md:flex-col md:items-end md:gap-2 md:*:pointer-events-auto">
        <MapToolbar
          showSearch={!wide}
          searchOpen={searchOpen}
          onSearch={() => setSearchOpen(!searchOpen)}
          onCopied={setCopied}
        />
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
          'pointer-events-none absolute top-3 bottom-3 left-3 flex max-md:bottom-12 max-w-[calc(100%-1.5rem)] flex-col items-start justify-end gap-2 *:pointer-events-auto',
          leftOpen && 'max-md:hidden md:left-[21.5rem] md:max-w-[calc(100%-22.25rem)]',
        )}
      >
        {selected && (
          <UnitCard unit={selected} onClose={() => useUi.getState().focusUnit(undefined)} />
        )}
        {selectedFire && (
          <FireCard observation={selectedFire} onClose={() => setSelectedFire(undefined)} />
        )}
        {showTimeline && <FireTimeline />}
        <CoordinatesBar map={mapRef} ready={ready} />
      </div>
      {/* Arriba al centro: herramienta activa, rótulo de la capa del mes y avisos, apilados */}
      <div className="pointer-events-none absolute top-14 left-1/2 flex w-max max-w-[calc(100%-1.5rem)] -translate-x-1/2 flex-col items-center gap-2 *:pointer-events-auto md:top-3 md:max-w-[min(32rem,calc(100%-30rem))]">
        {!wide && searchOpen && (
          <SearchBox className="w-[min(24rem,calc(100vw-1.5rem))]" autoFocus />
        )}
        {copied !== undefined && (
          <p
            role="status"
            className="m-0 flex items-center gap-2 rounded-md border border-line-strong bg-surface px-3 py-1.5 text-sm shadow-panel"
          >
            {copied ? (
              <>
                <Check size={16} strokeWidth={2} aria-hidden className="text-ok" />
                Enlace copiado
              </>
            ) : (
              'No se ha podido copiar: copia la dirección de la barra del navegador.'
            )}
          </p>
        )}
        {measure && (
          <section
            aria-label="Regla"
            className="flex flex-col gap-1.5 rounded-md border border-[#ffe066] bg-surface px-3 py-2 text-sm shadow-panel"
          >
            <p role="status" className="m-0 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
              <span>
                <span className="text-ink-muted">Distancia </span>
                <strong className="font-mono">{formatLength(measure.km)}</strong>
              </span>
              {measure.closed && (
                <span>
                  <span className="text-ink-muted">Superficie </span>
                  <strong className="font-mono">{formatArea(measure.km2)}</strong>
                </span>
              )}
            </p>
            <p className="m-0 text-xs text-ink-muted">
              {measure.closed
                ? 'Área cerrada. Borra para medir otra.'
                : 'Pulsa en el mapa para añadir puntos; pulsa el primero para cerrar el área. Esc para salir.'}
            </p>
            <div className="flex flex-wrap gap-2">
              {!measure.closed && measure.points >= 3 && (
                <Button onClick={measure.close}>Cerrar área</Button>
              )}
              {measure.points > 0 && (
                <Button variant="ghost" onClick={measure.clear}>
                  Borrar
                </Button>
              )}
              <Button variant="ghost" onClick={() => useUi.getState().setMapTool(null)}>
                <X size={16} strokeWidth={1.5} aria-hidden />
                Salir
              </Button>
            </div>
          </section>
        )}
        {tool === 'dibujar' && (
          <p
            role="status"
            className="m-0 flex items-center gap-2 rounded-md border border-accent bg-surface py-1 pr-1 pl-3 text-sm shadow-panel"
          >
            Pulsa dos esquinas del área en el mapa
            <Button size="md" onClick={() => useUi.getState().setMapTool(null)}>
              <X size={16} strokeWidth={1.5} aria-hidden />
              Cancelar
            </Button>
          </p>
        )}
        {layers.mes && manifest && (
          <p
            role="status"
            aria-label="Capa del mes del calendario"
            className="m-0 rounded-sm border border-ok/60 bg-surface px-2 py-1 text-xs font-semibold tracking-wide text-ok uppercase shadow-panel"
          >
            Real · FIRMS ·{' '}
            {formatMonth(manifest.tiempo.anioInicial + Math.floor(month / 12), month % 12)}
            {!grid && ' · cargando…'}
            {monthFc && monthFc.features.length === 0 && ' · sin detecciones'}
          </p>
        )}
        {tileError && (
          <p
            role="status"
            className="m-0 rounded-md border border-warn bg-surface px-3 py-1.5 text-sm"
          >
            Parte del mapa no se ha podido descargar. Comprueba la conexión; el resto sigue
            funcionando.
          </p>
        )}
      </div>
    </div>
  );
}
