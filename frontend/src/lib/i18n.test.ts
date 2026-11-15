import { describe, expect, it } from 'vitest';
import { AREA_PRESETS } from '../features/history/presets.ts';
import { UNIT } from '../features/history/model.ts';
import { METRIC_LABEL } from '../features/history/series.ts';
import { ANOMALY_LABEL } from '../features/history/stats.ts';
import { LEVEL } from '../map/alerts.ts';
import { KIND, STATUS } from '../map/markers.ts';
import { channelsFor, DOMAIN_LABEL, GROUPS, SCENARIO_LIST } from '../map/scenario.ts';
import en from './en.ts';
import { t, useLang } from './i18n.ts';

// Todo el código fuente como texto (Vite lo resuelve al compilar el test)
const FILES = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.ts', '!./en.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

/** Claves literales: t('…') en todo el código. */
function literalKeys(): string[] {
  const keys = new Set<string>();
  const rx = /\bt\(\s*'((?:[^'\\]|\\.)*)'/g;
  for (const text of Object.values(FILES)) {
    for (const m of text.matchAll(rx)) keys.add(m[1].replace(/\\'/g, "'"));
  }
  return [...keys];
}

/** Claves que llegan como datos (etiquetas de constantes, escenarios, áreas…). */
function dynamicKeys(): string[] {
  const scenario = SCENARIO_LIST[0];
  return [
    ...Object.values(KIND).map((k) => k.label),
    ...Object.values(STATUS).map((s) => s.label),
    ...Object.values(DOMAIN_LABEL),
    ...GROUPS,
    ...channelsFor(scenario).flatMap((c) => [c.name, c.last]),
    ...SCENARIO_LIST.flatMap((s) => [s.description, ...s.units.map((u) => u.name)]),
    ...AREA_PRESETS.map((a) => a.name),
    ...Object.values(UNIT),
    ...Object.values(METRIC_LABEL),
    ...Object.values(ANOMALY_LABEL),
    ...Object.values(LEVEL).map((l) => l.label),
  ];
}

describe('traducciones al inglés', () => {
  it('toda clave t() del código tiene traducción', () => {
    // Si el glob no encontrara el código, el test pasaría en falso
    expect(literalKeys().length).toBeGreaterThan(200);
    const missing = literalKeys().filter((k) => !(k in en));
    expect(missing).toEqual([]);
  });

  it('todo texto que llega como dato tiene traducción', () => {
    const missing = [...new Set(dynamicKeys())].filter((k) => !(k in en));
    expect(missing).toEqual([]);
  });

  it('las variables {x} de cada clave están también en la traducción', () => {
    const vars = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    const wrong = Object.entries(en).filter(([es, text]) => vars(es).join() !== vars(text).join());
    expect(wrong).toEqual([]);
  });

  it('t() traduce en inglés, sustituye variables y en español deja el texto', () => {
    expect(t('Capas')).toBe('Capas');
    expect(t('hace {d} días', { d: 3 })).toBe('hace 3 días');
    useLang.setState({ lang: 'en', dict: en });
    expect(t('Capas')).toBe('Layers');
    expect(t('hace {d} días', { d: 3 })).toBe('3 days ago');
    expect(t('texto sin traducir')).toBe('texto sin traducir');
    useLang.setState({ lang: 'es', dict: null });
  });
});
