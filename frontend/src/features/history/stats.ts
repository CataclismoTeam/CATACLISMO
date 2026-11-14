// Referencia histórica de un mes (mediana y percentiles del mismo mes en otros años) y anomalía.

/** Cuantil con interpolación lineal sobre valores ya ordenados. */
export function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) return Number.NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export interface Reference {
  /** Años usados como referencia y su valor */
  years: number[];
  values: number[];
  median: number;
  p10: number;
  p25: number;
  p75: number;
  p90: number;
}

export type AnomalyLevel =
  'muy por encima' | 'por encima' | 'normal' | 'por debajo' | 'sin referencia';

export interface Anomaly {
  level: AnomalyLevel;
  /** Diferencia con la mediana, en detecciones */
  difference: number;
  /** Diferencia relativa a la mediana; NaN si la mediana es 0 */
  ratio: number;
}

/** Con menos años que esto, la mediana no dice gran cosa. */
export const MIN_REFERENCE_YEARS = 5;

/**
 * Referencia del mes `mi`: el mismo mes del año en los demás años del rango,
 * contando solo los meses completos para no mezclar meses a medias.
 */
export function reference(
  values: ArrayLike<number>,
  mi: number,
  startYear: number,
  isComplete: (mi: number) => boolean,
  yearRange: [number, number],
): Reference {
  const years: number[] = [];
  const picked: number[] = [];
  for (let other = mi % 12; other < values.length; other += 12) {
    const year = startYear + Math.floor(other / 12);
    if (other === mi || year < yearRange[0] || year > yearRange[1] || !isComplete(other)) continue;
    years.push(year);
    picked.push(values[other]);
  }
  const sorted = [...picked].sort((a, b) => a - b);
  return {
    years,
    values: picked,
    median: quantile(sorted, 0.5),
    p10: quantile(sorted, 0.1),
    p25: quantile(sorted, 0.25),
    p75: quantile(sorted, 0.75),
    p90: quantile(sorted, 0.9),
  };
}

/**
 * Clasifica un mes frente a su referencia por percentiles, que aguantan bien series muy
 * asimétricas como la del fuego: por encima del P90 "muy por encima", del P75 "por encima",
 * por debajo del P25 "por debajo" y el resto "normal".
 */
export function anomaly(value: number, ref: Reference): Anomaly {
  const difference = value - ref.median;
  const ratio = ref.median > 0 ? difference / ref.median : Number.NaN;
  if (ref.values.length < MIN_REFERENCE_YEARS)
    return { level: 'sin referencia', difference, ratio };
  const level: AnomalyLevel =
    value > ref.p90
      ? 'muy por encima'
      : value > ref.p75
        ? 'por encima'
        : value < ref.p25
          ? 'por debajo'
          : 'normal';
  return { level, difference, ratio };
}

export const ANOMALY_LABEL: Record<AnomalyLevel, string> = {
  'muy por encima': 'Muy por encima',
  'por encima': 'Por encima',
  normal: 'Normal',
  'por debajo': 'Por debajo',
  'sin referencia': 'Sin referencia suficiente',
};
