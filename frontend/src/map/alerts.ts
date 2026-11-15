// Avisos de núcleos de población en riesgo (SIMULADO), a partir de las vías de escape del equipo.
import type { Route } from './scenario.ts';

export type AlertLevel = 'critico' | 'alto' | 'vigilancia';

/** Umbrales de margen (min) entre la evacuación y la llegada del fuego. */
export const CRITICAL_MIN = 30;
export const HIGH_MIN = 90;

export const LEVEL: Record<AlertLevel, { label: string; rule: string; color: string }> = {
  critico: {
    label: 'Crítico',
    rule: `margen menor de ${CRITICAL_MIN} min`,
    color: 'var(--color-fire)',
  },
  alto: { label: 'Alto', rule: `margen menor de ${HIGH_MIN} min`, color: 'var(--color-warn)' },
  vigilancia: {
    label: 'Vigilancia',
    rule: `margen de ${HIGH_MIN} min o más`,
    color: 'var(--color-water)',
  },
};

/** Sin margen calculado (no hay ruta que llegue antes que el fuego) cuenta como crítico. */
export function alertLevel(marginMin: number | null): AlertLevel {
  if (marginMin === null || marginMin < CRITICAL_MIN) return 'critico';
  return marginMin < HIGH_MIN ? 'alto' : 'vigilancia';
}

export interface Alert {
  route: Route;
  level: AlertLevel;
}

/** Avisos ordenados por la llegada del fuego: primero el núcleo al que antes llega. */
export function alertsFor(routes: Route[]): Alert[] {
  return [...routes]
    .sort((a, b) => a.llegadaFuegoMin - b.llegadaFuegoMin)
    .map((route) => ({ route, level: alertLevel(route.margenMin) }));
}

/** «45 min» o «4 h 17 min». */
export function minutes(total: number): string {
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

/** Rectángulo [oeste, sur, este, norte] de una ruta. */
export function routeBbox(route: Route): [number, number, number, number] {
  const lons = route.coords.map((c) => c[0]);
  const lats = route.coords.map((c) => c[1]);
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}
