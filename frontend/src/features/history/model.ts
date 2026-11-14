// Modelo derivado del calendario: todo lo que pintan la tabla, la ficha y el gráfico.
import { useMemo } from 'react';
import type { Manifest } from '../../data/types.ts';
import { useHistory } from '../../store/history.ts';
import { monthInfo, type Metric, type MonthInfo, type Series } from './series.ts';
import { anomaly, quantile, reference, type Anomaly, type Reference } from './stats.ts';

export interface CalendarModel {
  manifest: Manifest;
  series: Series;
  metric: Metric;
  values: Float64Array;
  infos: MonthInfo[];
  years: number[];
  yearRange: [number, number];
  /** Máximo mensual del rango: tope de la escala de color */
  max: number;
  total: number;
  yearTotals: number[];
  /** Mediana de cada mes del año con los meses completos del rango */
  monthMedians: number[];
  selected: number;
  selectedYear: number;
  selectedMonth: number;
  value: number;
  info: MonthInfo;
  reference: Reference;
  anomaly: Anomaly;
}

export const UNIT: Record<Metric, string> = {
  h: 'detecciones equivalentes MODIS',
  m: 'detecciones MODIS',
  v: 'detecciones VIIRS',
};

export function buildModel(
  manifest: Manifest,
  series: Series,
  metric: Metric,
  selected: number,
  yearRange: [number, number],
): CalendarModel {
  const values = series[metric];
  const start = series.startYear;
  const infos = Array.from(values, (_, mi) => monthInfo(manifest, mi));
  const years: number[] = [];
  for (let y = yearRange[0]; y <= yearRange[1]; y++) years.push(y);

  let max = 0;
  let total = 0;
  const yearTotals = years.map((year) => {
    let sum = 0;
    for (let m = 0; m < 12; m++) {
      const mi = (year - start) * 12 + m;
      if (infos[mi].state === 'sin datos') continue;
      sum += values[mi];
      max = Math.max(max, values[mi]);
    }
    total += sum;
    return sum;
  });

  const monthMedians = Array.from({ length: 12 }, (_, m) => {
    const complete = years
      .map((year) => (year - start) * 12 + m)
      .filter((mi) => infos[mi].state === 'completo')
      .map((mi) => values[mi])
      .sort((a, b) => a - b);
    return quantile(complete, 0.5);
  });

  const ref = reference(values, selected, start, (mi) => infos[mi].state === 'completo', yearRange);
  return {
    manifest,
    series,
    metric,
    values,
    infos,
    years,
    yearRange,
    max,
    total,
    yearTotals,
    monthMedians,
    selected,
    selectedYear: start + Math.floor(selected / 12),
    selectedMonth: selected % 12,
    value: values[selected],
    info: infos[selected],
    reference: ref,
    anomaly: anomaly(values[selected], ref),
  };
}

/** Modelo del calendario con el estado actual, o `undefined` mientras faltan datos. */
export function useCalendarModel(): CalendarModel | undefined {
  const manifest = useHistory((s) => s.manifest);
  const series = useHistory((s) => s.series);
  const metric = useHistory((s) => s.metric);
  const selected = useHistory((s) => s.selected);
  const yearRange = useHistory((s) => s.yearRange);
  return useMemo(
    () =>
      manifest && series ? buildModel(manifest, series, metric, selected, yearRange) : undefined,
    [manifest, series, metric, selected, yearRange],
  );
}
