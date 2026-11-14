import { create } from 'zustand';
import { readStored, writeStored } from '../lib/storage.ts';

export type MapMode = '2d' | '3d';
export type Basemap = 'satelite' | 'topografico' | 'oscuro';
export type ScenarioId = 'forestal' | 'urbano';
export type LayerId =
  'detecciones' | 'incendio' | 'prediccion' | 'unidades' | 'evacuacion' | 'curvas' | 'sombreado';

export const DEFAULT_LAYERS: Record<LayerId, boolean> = {
  detecciones: true,
  incendio: true,
  prediccion: true,
  unidades: true,
  evacuacion: true,
  curvas: false,
  sombreado: false,
};

/** Encuadre pedido desde fuera del mapa (lista de incendios). `at` fuerza repetirlo. */
export interface FlyTarget {
  bbox: [number, number, number, number];
  at: number;
}

interface UiState {
  briefingOpen: boolean;
  calendarOpen: boolean;
  methodOpen: boolean;
  projection: boolean;
  radioOpen: boolean;
  layersOpen: boolean;
  incidentsOpen: boolean;
  selectedIncident?: string;
  flyTarget?: FlyTarget;
  mapMode: MapMode;
  /** Exageración del relieve en 3D: 1 = real; con más inclinación da la vista 2.5D */
  exaggeration: number;
  basemap: Basemap;
  scenario: ScenarioId;
  layers: Record<LayerId, boolean>;
  closeBriefing: () => void;
  openBriefing: () => void;
  setCalendarOpen: (open: boolean) => void;
  setMethodOpen: (open: boolean) => void;
  setRadioOpen: (open: boolean) => void;
  setLayersOpen: (open: boolean) => void;
  setIncidentsOpen: (open: boolean) => void;
  focusIncident: (id: string | undefined, bbox?: [number, number, number, number]) => void;
  toggleProjection: () => void;
  setMapMode: (mode: MapMode) => void;
  setExaggeration: (value: number) => void;
  setBasemap: (basemap: Basemap) => void;
  setScenario: (scenario: ScenarioId) => void;
  toggleLayer: (id: LayerId) => void;
}

const BRIEFING_KEY = 'cataclismo.briefing-visto';
const PROJECTION_KEY = 'cataclismo.proyeccion';
const MAP_KEY = 'cataclismo.mapa';

const narrow = () => typeof window !== 'undefined' && window.innerWidth < 768;
const storedMap = readStored<{ mode?: MapMode; basemap?: Basemap }>(MAP_KEY, {});

export const useUi = create<UiState>((set, get) => ({
  briefingOpen: !readStored(BRIEFING_KEY, false),
  // En pantallas estrechas el mapa va primero y el calendario empieza plegado
  calendarOpen: !narrow(),
  methodOpen: false,
  projection: readStored(PROJECTION_KEY, false),
  radioOpen: false,
  // Capas plegado de inicio: el mapa necesita el espacio; se abre con su botón
  layersOpen: false,
  incidentsOpen: !narrow(),
  mapMode: storedMap.mode === '2d' ? '2d' : '3d',
  exaggeration: 1.2,
  basemap: storedMap.basemap ?? 'satelite',
  scenario: 'forestal',
  layers: DEFAULT_LAYERS,
  closeBriefing: () => {
    writeStored(BRIEFING_KEY, true);
    set({ briefingOpen: false });
  },
  openBriefing: () => set({ briefingOpen: true }),
  setCalendarOpen: (calendarOpen) => set({ calendarOpen }),
  setMethodOpen: (methodOpen) => set({ methodOpen }),
  setRadioOpen: (radioOpen) => set({ radioOpen }),
  setLayersOpen: (layersOpen) => set({ layersOpen }),
  setIncidentsOpen: (incidentsOpen) => set({ incidentsOpen }),
  focusIncident: (selectedIncident, bbox) =>
    set({
      selectedIncident,
      ...(bbox && { flyTarget: { bbox, at: Date.now() } }),
      // En móvil la lista ocupa media pantalla: se pliega para ver el incendio y su ficha
      ...(selectedIncident && narrow() && { incidentsOpen: false }),
    }),
  toggleProjection: () => {
    const projection = !get().projection;
    writeStored(PROJECTION_KEY, projection);
    set({ projection });
  },
  setMapMode: (mapMode) => {
    writeStored(MAP_KEY, { mode: mapMode, basemap: get().basemap });
    set({ mapMode });
  },
  setExaggeration: (exaggeration) => set({ exaggeration }),
  setBasemap: (basemap) => {
    writeStored(MAP_KEY, { mode: get().mapMode, basemap });
    // Las curvas de nivel son la razón de ser del topográfico: se encienden con él
    set({
      basemap,
      layers: { ...get().layers, curvas: basemap === 'topografico' || get().layers.curvas },
    });
  },
  setScenario: (scenario) => set({ scenario }),
  toggleLayer: (id) => set({ layers: { ...get().layers, [id]: !get().layers[id] } }),
}));
