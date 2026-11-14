// Serie mensual de un área: suma de las celdas incluidas. Aquí no se armoniza nada,
// solo se agregan los conteos ya calibrados por tools/build-hotspots.
import type { GridData, Manifest } from '../../data/types.ts';

export interface Series {
  startYear: number;
  /** Detecciones equivalentes MODIS */
  h: Float64Array;
  m: Float64Array;
  v: Float64Array;
  /** Suma de FRP (MW) de cada sensor */
  frpM: Float64Array;
  frpV: Float64Array;
}

export type Metric = 'h' | 'm' | 'v';

export const METRIC_LABEL: Record<Metric, string> = {
  h: 'Armonizado',
  m: 'Solo MODIS',
  v: 'Solo VIIRS',
};

/** Serie de toda el área publicada, directa del manifiesto (sin descargar la rejilla). */
export function seriesFromManifest(manifest: Manifest): Series {
  const t = manifest.totalesMensuales;
  const empty = () => new Float64Array(manifest.tiempo.meses).fill(Number.NaN);
  return {
    startYear: manifest.tiempo.anioInicial,
    h: Float64Array.from(t.armonizado),
    m: Float64Array.from(t.modis),
    v: Float64Array.from(t.viirs),
    frpM: empty(),
    frpV: empty(),
  };
}

export function aggregate(grid: GridData, mask: Uint8Array | null, manifest: Manifest): Series {
  const { anioInicial, meses } = manifest.tiempo;
  const series: Series = {
    startYear: anioInicial,
    h: new Float64Array(meses),
    m: new Float64Array(meses),
    v: new Float64Array(meses),
    frpM: new Float64Array(meses),
    frpV: new Float64Array(meses),
  };
  for (const chunk of grid.years) {
    const offset = (chunk.year - anioInicial) * 12;
    for (let i = 0; i < chunk.n; i++) {
      if (mask && mask[chunk.cell[i]] === 0) continue;
      const mi = offset + chunk.month[i];
      series.h[mi] += chunk.h[i];
      series.m[mi] += chunk.m[i];
      series.v[mi] += chunk.v[i];
      series.frpM[mi] += chunk.frpM[i];
      series.frpV[mi] += chunk.frpV[i];
    }
  }
  return series;
}

export type MonthState = 'completo' | 'parcial' | 'sin datos';

export interface MonthInfo {
  state: MonthState;
  daysCovered: number;
  daysInMonth: number;
  /** El mes incluye datos NRT, que pueden cambiar al consolidarse */
  provisional: boolean;
  sensors: 'MODIS+VIIRS' | 'MODIS' | 'VIIRS' | '';
}

export function monthInfo(manifest: Manifest, mi: number): MonthInfo {
  const t = manifest.tiempo;
  const dim = t.diasDelMes[mi];
  const modis = t.diasCubiertos.MODIS[mi];
  const viirs = t.diasCubiertos.VIIRS[mi];
  const active = [modis, viirs].filter((d) => d > 0);
  const covered = active.length ? Math.min(...active) : 0;
  return {
    state: covered === 0 ? 'sin datos' : covered === dim ? 'completo' : 'parcial',
    daysCovered: covered,
    daysInMonth: dim,
    provisional: t.provisional[mi] > 0,
    sensors:
      modis > 0 && viirs > 0 ? 'MODIS+VIIRS' : modis > 0 ? 'MODIS' : viirs > 0 ? 'VIIRS' : '',
  };
}

/** Último mes con algún dato: el "mes en curso" de la serie. */
export function lastMonthWithData(manifest: Manifest): number {
  for (let mi = manifest.tiempo.meses - 1; mi >= 0; mi--) {
    if (monthInfo(manifest, mi).state !== 'sin datos') return mi;
  }
  return 0;
}

export function lastCompleteMonth(manifest: Manifest): number {
  for (let mi = manifest.tiempo.meses - 1; mi >= 0; mi--) {
    if (monthInfo(manifest, mi).state === 'completo') return mi;
  }
  return 0;
}
