import {
  Cartesian2,
  Cartesian3,
  Cartographic,
  Color,
  HorizontalOrigin,
  ImageryLayer,
  OpenStreetMapImageryProvider,
  Rectangle,
  SceneMode,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  UrlTemplateImageryProvider,
  VerticalOrigin,
  Viewer,
  WebMapServiceImageryProvider,
} from 'cesium';
import { Compass, Layers3, MousePointer2, Pentagon, RectangleHorizontal } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { useHistory } from '../store/history.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { cn } from '../lib/cn.ts';
import { OperationalDeck } from './OperationalDeck.tsx';
import { ThreeBeacon } from './ThreeBeacon.tsx';

const SPAIN_VIEW = Rectangle.fromDegrees(-19, 27, 5.5, 44.5);

type LayerId = 'perimeter' | 'units' | 'wind' | 'hotspots';
const LAYER_LABELS: Record<LayerId, string> = {
  perimeter: 'Perímetro del incidente',
  units: 'Unidades desplegadas',
  wind: 'Viento y dirección',
  hotspots: 'Detecciones satélite',
};

function providerFor(imagery: 'satellite' | 'topographic' | 'dark') {
  if (imagery === 'satellite') {
    return new UrlTemplateImageryProvider({
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    });
  }
  if (imagery === 'topographic') {
    return new WebMapServiceImageryProvider({
      url: 'https://ows.mundialis.de/services/service?',
      layers: 'TOPO-OSM-WMS',
      parameters: { format: 'image/png', transparent: false },
    });
  }
  return new OpenStreetMapImageryProvider({ url: 'https://tile.openstreetmap.org/' });
}

function marker(viewer: Viewer, lon: number, lat: number, label: string, color: Color) {
  return viewer.entities.add({
    position: Cartesian3.fromDegrees(lon, lat),
    point: { pixelSize: 10, color, outlineColor: Color.WHITE, outlineWidth: 1 },
    label: {
      text: label,
      font: '12px Inter',
      fillColor: Color.WHITE,
      showBackground: true,
      backgroundColor: Color.fromCssColorString('#12171edd'),
      horizontalOrigin: HorizontalOrigin.CENTER,
      verticalOrigin: VerticalOrigin.BOTTOM,
      pixelOffset: new Cartesian2(0, -12),
    },
  });
}

export default function Globe() {
  const container = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer | undefined>(undefined);
  const [activeLayers, setActiveLayers] = useState<Record<LayerId, boolean>>({
    perimeter: true,
    units: true,
    wind: true,
    hotspots: false,
  });
  const [opacity, setOpacity] = useState(0.85);
  const [pendingPoints, setPendingPoints] = useState<[number, number][]>([]);
  const mapMode = useUi((s) => s.mapMode);
  const imagery = useUi((s) => s.imagery);
  const layersOpen = useUi((s) => s.layersOpen);
  const drawing = useUi((s) => s.drawing);
  const setMapMode = useUi((s) => s.setMapMode);
  const setImagery = useUi((s) => s.setImagery);
  const setLayersOpen = useUi((s) => s.setLayersOpen);
  const setDrawing = useUi((s) => s.setDrawing);
  const scenario = useUi((s) => s.scenario);
  const setScenario = useUi((s) => s.setScenario);
  const setArea = useHistory((s) => s.setArea);

  useEffect(() => {
    if (!container.current) return;
    const viewer = new Viewer(container.current, {
      baseLayer: new ImageryLayer(providerFor('dark')),
      baseLayerPicker: false,
      geocoder: false,
      timeline: false,
      animation: false,
      homeButton: false,
      navigationHelpButton: false,
      sceneModePicker: false,
      fullscreenButton: false,
      selectionIndicator: false,
      infoBox: false,
    });
    viewer.camera.setView({ destination: SPAIN_VIEW });
    viewerRef.current = viewer;
    return () => {
      viewerRef.current = undefined;
      viewer.destroy();
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.imageryLayers.removeAll();
    viewer.imageryLayers.addImageryProvider(providerFor(imagery));
  }, [imagery]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    if (mapMode === '2d') viewer.scene.mode = SceneMode.SCENE2D;
    else if (mapMode === '2.5d') viewer.scene.morphToColumbusView(0.5);
    else viewer.scene.morphTo3D(0.5);
  }, [mapMode]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || drawing === 'none') return;
    const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
    const points: [number, number][] = [];
    const addPoint = (position: Cartesian2) => {
      const ray = viewer.camera.getPickRay(position);
      const picked = ray ? viewer.scene.globe.pick(ray, viewer.scene) : undefined;
      if (!picked) return;
      const cartographic = Cartographic.fromCartesian(picked);
      points.push([
        cartographic.longitude * (180 / Math.PI),
        cartographic.latitude * (180 / Math.PI),
      ]);
      setPendingPoints([...points]);
      if (drawing === 'rectangle' && points.length === 2) {
        const [a, b] = points;
        const west = Math.min(a[0], b[0]);
        const east = Math.max(a[0], b[0]);
        const south = Math.min(a[1], b[1]);
        const north = Math.max(a[1], b[1]);
        setArea({ kind: 'bbox', name: 'Rectángulo del mapa', west, south, east, north });
        setDrawing('none');
        setPendingPoints([]);
      }
    };
    handler.setInputAction(
      (event: { position: Cartesian2 }) => addPoint(event.position),
      ScreenSpaceEventType.LEFT_CLICK,
    );
    handler.setInputAction(() => {
      if (drawing === 'polygon' && points.length >= 3) {
        const ring = [...points, points[0]] as [number, number][];
        setArea({ kind: 'polygon', name: 'Polígono del mapa', ring });
        setDrawing('none');
        setPendingPoints([]);
      }
    }, ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
    return () => handler.destroy();
  }, [drawing, setArea, setDrawing]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.entities.removeAll();
    if (activeLayers.perimeter) {
      viewer.entities.add({
        polygon: {
          hierarchy: Cartesian3.fromDegreesArray([
            -5.34, 36.55, -5.05, 36.55, -5.0, 36.7, -5.27, 36.79, -5.45, 36.68,
          ]),
          material: Color.fromCssColorString('#ff704366').withAlpha(opacity),
          outline: true,
          outlineColor: Color.fromCssColorString('#ff7043'),
        },
      });
      viewer.entities.add({
        position: Cartesian3.fromDegrees(-5.23, 36.68),
        label: {
          text: 'Incendio Sierra Bermeja',
          fillColor: Color.WHITE,
          showBackground: true,
          verticalOrigin: VerticalOrigin.CENTER,
        },
      });
    }
    if (activeLayers.units) {
      marker(viewer, -5.2, 36.67, 'BRIF-01', Color.fromCssColorString('#62a8ff'));
      marker(viewer, -5.08, 36.61, 'UME-04', Color.fromCssColorString('#4cc98c'));
      marker(viewer, -5.38, 36.71, 'PM-2', Color.fromCssColorString('#ffb833'));
    }
    if (activeLayers.wind) {
      viewer.entities.add({
        polyline: {
          positions: Cartesian3.fromDegreesArray([-5.7, 36.5, -5.15, 36.67]),
          width: 4,
          material: Color.fromCssColorString('#3fc8de').withAlpha(opacity),
        },
      });
      viewer.entities.add({
        position: Cartesian3.fromDegrees(-5.65, 36.53),
        label: {
          text: 'NW 18 km/h',
          fillColor: Color.fromCssColorString('#3fc8de'),
          showBackground: true,
        },
      });
    }
    if (activeLayers.hotspots)
      marker(viewer, -5.17, 36.69, 'Foco activo', Color.fromCssColorString('#ff7043'));
  }, [activeLayers, opacity, scenario]);

  const toggleLayer = (id: LayerId) =>
    setActiveLayers((current) => ({ ...current, [id]: !current[id] }));

  return (
    <div className="absolute inset-0">
      <div ref={container} className="absolute inset-0" data-testid="globo" />
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="absolute left-4 top-4 z-(--z-panel) flex flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-[#0f141c]/95 p-1.5 shadow-panel backdrop-blur-md"
      >
        {(['2d', '2.5d', '3d'] as const).map((mode) => (
          <Button
            key={mode}
            size="md"
            variant={mapMode === mode ? 'primary' : 'ghost'}
            aria-pressed={mapMode === mode}
            onClick={() => setMapMode(mode)}
            className="h-8 px-2.5 text-xs"
          >
            {mode.toUpperCase()}
          </Button>
        ))}
        <select
          className="h-8 rounded-md border border-white/10 bg-canvas px-2 text-xs text-ink"
          value={imagery}
          onChange={(event) => setImagery(event.target.value as typeof imagery)}
          aria-label="Fondo cartográfico"
        >
          <option value="satellite">Satélite</option>
          <option value="topographic">Topográfico</option>
          <option value="dark">Oscuro</option>
        </select>
        <select
          className="h-8 rounded-md border border-white/10 bg-canvas px-2 text-xs text-ink"
          value={scenario}
          onChange={(event) => setScenario(event.target.value as typeof scenario)}
          aria-label="Escenario"
        >
          <option value="fire">Incendio forestal</option>
          <option value="flood">Inundación</option>
          <option value="mci">Múltiples víctimas</option>
          <option value="intermunicipal">Intermunicipal</option>
        </select>
      </motion.div>
      <div className="absolute right-4 top-4 z-(--z-panel) flex flex-col gap-2">
        <Button
          size="icon"
          className="border-white/10 bg-[#0f141c]/95 shadow-panel backdrop-blur-md"
          aria-label="Abrir gestor de capas"
          aria-pressed={layersOpen}
          onClick={() => setLayersOpen(!layersOpen)}
        >
          <Layers3 size={18} aria-hidden />
        </Button>
        <Button
          size="icon"
          className="border-white/10 bg-[#0f141c]/95 shadow-panel backdrop-blur-md"
          aria-label="Orientación norte"
        >
          <Compass size={18} aria-hidden />
        </Button>
      </div>
      <AnimatePresence>
        {layersOpen && (
          <motion.aside
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 16 }}
            className="absolute right-4 top-28 z-(--z-panel) w-72 rounded-xl border border-white/10 bg-[#0f141c]/95 p-4 shadow-panel backdrop-blur-md"
          >
            <div className="mb-3 flex items-start justify-between">
              <div>
                <p className="m-0 text-[10px] font-semibold uppercase tracking-[0.18em] text-accent">
                  Control operativo
                </p>
                <h2 className="m-0 mt-1 text-sm font-semibold">Capas y escenario</h2>
              </div>
              <span className="rounded-full bg-fire/15 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-fire">
                Activo
              </span>
            </div>
            <div className="flex flex-col gap-2">
              {(Object.keys(LAYER_LABELS) as LayerId[]).map((id) => (
                <label key={id} className="flex items-center justify-between gap-2 text-sm">
                  <span>{LAYER_LABELS[id]}</span>
                  <input
                    type="checkbox"
                    checked={activeLayers[id]}
                    onChange={() => toggleLayer(id)}
                  />
                </label>
              ))}
              <label className="flex flex-col gap-1 text-xs text-ink-muted">
                Opacidad
                <input
                  type="range"
                  min="0.2"
                  max="1"
                  step="0.05"
                  value={opacity}
                  onChange={(event) => setOpacity(Number(event.target.value))}
                />
              </label>
            </div>
            <div className="mt-3 border-t border-line pt-3">
              <p className="m-0 mb-2 text-xs text-ink-muted">Dibujar área para el calendario</p>
              <div className="flex gap-2">
                <Button
                  size="icon"
                  aria-label="Dibujar polígono"
                  aria-pressed={drawing === 'polygon'}
                  onClick={() => setDrawing(drawing === 'polygon' ? 'none' : 'polygon')}
                >
                  <Pentagon size={17} aria-hidden />
                </Button>
                <Button
                  size="icon"
                  aria-label="Dibujar rectángulo"
                  aria-pressed={drawing === 'rectangle'}
                  onClick={() => setDrawing(drawing === 'rectangle' ? 'none' : 'rectangle')}
                >
                  <RectangleHorizontal size={17} aria-hidden />
                </Button>
                {drawing !== 'none' && (
                  <span className="flex items-center text-xs text-accent">
                    <MousePointer2 size={14} className="mr-1" aria-hidden />
                    {pendingPoints.length} puntos
                  </span>
                )}
              </div>
            </div>
            <div
              className={cn(
                'mt-3 flex items-center justify-between rounded-lg bg-raised p-2 text-xs text-ink-muted',
                scenario === 'fire' && 'border-l-2 border-fire',
              )}
            >
              <div>
                <strong className="text-ink">Sierra Bermeja</strong>
                <br />
                {scenario === 'fire' ? 'Incendio forestal · activo' : 'Datos simulados'}
              </div>
              <ThreeBeacon />
            </div>
            <div className="mt-3 border-t border-line pt-3">
              <p className="m-0 text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-muted">
                Vista táctica
              </p>
              <OperationalDeck />
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
      {drawing !== 'none' && (
        <div className="absolute bottom-3 left-1/2 z-(--z-panel) -translate-x-1/2 rounded-md bg-surface/95 px-3 py-2 text-sm shadow-panel">
          Haz clic para marcar el área
          {drawing === 'polygon' ? ' y doble clic para cerrar' : ' con dos esquinas'}.
        </div>
      )}
    </div>
  );
}
