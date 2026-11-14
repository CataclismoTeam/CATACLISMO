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
import { loadDetections, type Detections } from './detections.ts';
import { LayersPanel } from './LayersPanel.tsx';
import { ignitionElement, meetingElement, unitElement } from './markers.ts';
import { IncidentsPanel } from './IncidentsPanel.tsx';
import { loadIncidents, type IncidentsFile } from './incidents.ts';
import { applyVisibility, FAR_ZOOM, installOverlays } from './overlays.ts';
import { provider } from './providers.ts';
import { SCENARIOS, type Unit } from './scenario.ts';
import {
  CoordinatesBar,
  FireCard,
  IncidentCard,
  UnitCard,
  type FireObservation,
} from './MapHud.tsx';

setWorkerUrl(workerUrl);

const PITCH_3D = 60;
const SIMULATIONS = Object.values(SCENARIOS);

/** Mapa de mando: un único MapLibre que cambia de estilo, relieve y cámara sin recrearse. */
export default function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibre | null>(null);
  const markers = useRef<Marker[]>([]);
  const [ready, setReady] = useState(false);
  const [detections, setDetections] = useState<Detections>();
  const [selected, setSelected] = useState<Unit>();
  const [selectedFire, setSelectedFire] = useState<FireObservation>();
  const [tileError, setTileError] = useState(false);
  const [incidents, setIncidents] = useState<IncidentsFile>();
  const [far, setFar] = useState(false);
  const selectedIncidentId = useUi((s) => s.selectedIncident);
  const focusIncident = useUi((s) => s.focusIncident);
  const flyTarget = useUi((s) => s.flyTarget);
  const selectedIncident = incidents?.incendios.find((i) => i.id === selectedIncidentId);

  const mode = useUi((s) => s.mapMode);
  const exaggeration = useUi((s) => s.exaggeration);
  const basemap = useUi((s) => s.basemap);
  const scenarioId = useUi((s) => s.scenario);
  const layers = useUi((s) => s.layers);
  const scenario = SCENARIOS[scenarioId];

  // Estado vivo para los manejadores de MapLibre (se registran una sola vez)
  const live = useRef({
    scenario,
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
    map.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left');

    map.on('style.load', () => {
      const s = live.current;
      installOverlays(map, s.scenario, s.simulations, s.detections, s.incidents, s.layers);
      map.setTerrain(s.mode === '3d' ? { source: 'dem', exaggeration: s.exaggeration } : null);
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
        setSelected(undefined);
      });
      setReady(true);
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
        setSelected(undefined);
        setSelectedFire(undefined);
      }
    });

    loadDetections()
      .then(setDetections)
      .catch(() => setDetections(undefined));
    loadIncidents()
      .then(setIncidents)
      .catch(() => setIncidents(undefined));

    // Vista lejana: fuera rótulos y marcadores, solo un icono por incendio
    const onZoom = () => setFar(map.getZoom() < FAR_ZOOM);
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
        if (layer === 'sim-icon' && (id === 'forestal' || id === 'urbano')) {
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
    installOverlays(map, scenario, SIMULATIONS, detections, incidents, live.current.layers);
  }, [scenario, detections, incidents, ready]);

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
    setSelected(undefined);
  }, [scenario]);

  // Esc cierra cualquier ficha abierta
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      setSelected(undefined);
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
      for (const unit of scenario.units) add(unitElement(unit, setSelected), [unit.lon, unit.lat]);
    }
    if (layers.evacuacion) {
      for (const route of scenario.routes) {
        add(meetingElement(route.meeting), route.coords.at(-1) ?? route.coords[0], 'bottom');
      }
    }
    if (layers.incendio) add(ignitionElement(), scenario.ignition, 'bottom');
  }, [scenario, layers.unidades, layers.evacuacion, layers.incendio]);

  return (
    <div className={cn('absolute inset-0', far && 'map-far')}>
      {/* Estilo en línea: la hoja de MapLibre (sin capa) pondría position: relative */}
      <div ref={container} style={{ position: 'absolute', inset: 0 }} data-testid="mapa" />
      {!ready && (
        <p role="status" className="map-placeholder absolute inset-0 m-0 grid place-items-center">
          <span className="rounded-sm bg-canvas px-3 py-1.5">Cargando el mapa…</span>
        </p>
      )}
      <IncidentsPanel incidents={incidents} />
      <LayersPanel detections={detections} />
      {selectedIncident && (
        <IncidentCard incident={selectedIncident} onClose={() => focusIncident(undefined)} />
      )}
      {selected && <UnitCard unit={selected} onClose={() => setSelected(undefined)} />}
      {selectedFire && (
        <FireCard observation={selectedFire} onClose={() => setSelectedFire(undefined)} />
      )}
      <CoordinatesBar map={mapRef} ready={ready} />
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
