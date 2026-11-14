import { create } from 'zustand';
import { readStored, writeStored } from '../lib/storage.ts';

interface UiState {
  briefingOpen: boolean;
  mapOpen: boolean;
  calendarOpen: boolean;
  methodOpen: boolean;
  projection: boolean;
  mapMode: '2d' | '2.5d' | '3d';
  imagery: 'satellite' | 'topographic' | 'dark';
  layersOpen: boolean;
  drawing: 'none' | 'polygon' | 'rectangle';
  scenario: 'fire' | 'flood' | 'mci' | 'intermunicipal';
  closeBriefing: () => void;
  openBriefing: () => void;
  openMap: () => void;
  setCalendarOpen: (open: boolean) => void;
  setMethodOpen: (open: boolean) => void;
  toggleProjection: () => void;
  setMapMode: (mapMode: UiState['mapMode']) => void;
  setImagery: (imagery: UiState['imagery']) => void;
  setLayersOpen: (layersOpen: boolean) => void;
  setDrawing: (drawing: UiState['drawing']) => void;
  setScenario: (scenario: UiState['scenario']) => void;
}

const BRIEFING_KEY = 'cataclismo.briefing-visto';
const PROJECTION_KEY = 'cataclismo.proyeccion';

export const useUi = create<UiState>((set, get) => ({
  briefingOpen: !readStored(BRIEFING_KEY, false),
  mapOpen: false,
  calendarOpen: true,
  methodOpen: false,
  projection: readStored(PROJECTION_KEY, false),
  mapMode: '3d',
  imagery: 'dark',
  layersOpen: true,
  drawing: 'none',
  scenario: 'fire',
  closeBriefing: () => {
    writeStored(BRIEFING_KEY, true);
    set({ briefingOpen: false });
  },
  openBriefing: () => set({ briefingOpen: true }),
  openMap: () => set({ mapOpen: true }),
  setCalendarOpen: (calendarOpen) => set({ calendarOpen }),
  setMethodOpen: (methodOpen) => set({ methodOpen }),
  toggleProjection: () => {
    const projection = !get().projection;
    writeStored(PROJECTION_KEY, projection);
    set({ projection });
  },
  setMapMode: (mapMode) => set({ mapMode }),
  setImagery: (imagery) => set({ imagery }),
  setLayersOpen: (layersOpen) => set({ layersOpen }),
  setDrawing: (drawing) => set({ drawing }),
  setScenario: (scenario) => set({ scenario }),
}));
