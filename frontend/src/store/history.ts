import { create } from 'zustand';
import { DataError, dataSource } from '../data/source.ts';
import type { GridData, Manifest } from '../data/types.ts';
import { areaCells, SPAIN, type Area, type AreaCells } from '../features/history/area.ts';
import {
  aggregate,
  lastMonthWithData,
  seriesFromManifest,
  type Metric,
  type Series,
} from '../features/history/series.ts';

type Status = 'cargando' | 'listo' | 'error';

interface HistoryState {
  status: Status;
  error?: string;
  /** La rejilla por celdas llega después del manifiesto: hace falta para áreas y FRP */
  gridStatus: Status;
  manifest?: Manifest;
  grid?: GridData;
  area: Area;
  cells?: AreaCells;
  series?: Series;
  /** Índice del mes seleccionado (0 = enero del año inicial) */
  selected: number;
  yearRange: [number, number];
  metric: Metric;
  load: () => Promise<void>;
  setArea: (area: Area) => void;
  select: (mi: number) => void;
  setYearRange: (range: [number, number]) => void;
  setMetric: (metric: Metric) => void;
}

const message = (error: unknown) =>
  error instanceof DataError ? error.message : 'Los datos no tienen el formato esperado.';

function compute(area: Area, manifest: Manifest, grid: GridData) {
  const cells = areaCells(area, manifest.rejilla, grid.cells);
  return { cells, series: aggregate(grid, area.kind === 'all' ? null : cells.mask, manifest) };
}

export const useHistory = create<HistoryState>((set, get) => ({
  status: 'cargando',
  gridStatus: 'cargando',
  area: SPAIN,
  selected: 0,
  yearRange: [0, 0],
  metric: 'h',

  load: async () => {
    set({ status: 'cargando', gridStatus: 'cargando', error: undefined });
    let manifest: Manifest;
    try {
      manifest = await dataSource.manifest();
    } catch (error) {
      set({ status: 'error', gridStatus: 'error', error: message(error) });
      return;
    }
    const { anioInicial, meses } = manifest.tiempo;
    set({
      status: 'listo',
      manifest,
      // Toda España se pinta ya con los totales del manifiesto, sin esperar a la rejilla
      series: get().area.kind === 'all' ? seriesFromManifest(manifest) : undefined,
      selected: lastMonthWithData(manifest),
      yearRange: [anioInicial, anioInicial + meses / 12 - 1],
    });
    try {
      const grid = await dataSource.grid(manifest);
      set({ gridStatus: 'listo', grid, ...compute(get().area, manifest, grid) });
    } catch (error) {
      set({ gridStatus: 'error', error: message(error) });
    }
  },

  setArea: (area) => {
    const { manifest, grid } = get();
    if (manifest && grid) set({ area, ...compute(area, manifest, grid) });
    else set({ area, cells: undefined, series: undefined });
  },
  select: (selected) => set({ selected }),
  setYearRange: (yearRange) => {
    // El mes seleccionado se mantiene dentro del rango visible (mismo mes, año más cercano)
    const { selected, manifest } = get();
    const start = manifest?.tiempo.anioInicial ?? yearRange[0];
    const year = Math.min(yearRange[1], Math.max(yearRange[0], start + Math.floor(selected / 12)));
    set({ yearRange, selected: (year - start) * 12 + (selected % 12) });
  },
  setMetric: (metric) => set({ metric }),
}));
