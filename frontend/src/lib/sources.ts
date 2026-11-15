// Fuentes de los datos y de la cartografía, con enlace. Se citan en el briefing, en la ficha del
// incendio, en el panel de procedencia y en la metodología.
import { locale, t } from './i18n.ts';
export interface Source {
  name: string;
  url: string;
  what: string;
}

export const SOURCES = {
  firms: {
    name: 'NASA FIRMS',
    url: 'https://firms.modaps.eosdis.nasa.gov/',
    what: 'Fire Information for Resource Management System: focos de calor detectados por satélite.',
  },
  viirs: {
    name: 'VIIRS (375 m)',
    url: 'https://www.earthdata.nasa.gov/data/instruments/viirs',
    what: 'Sensor de los satélites Suomi NPP, NOAA-20 y NOAA-21; píxel de unos 375 m.',
  },
  modis: {
    name: 'MODIS (1 km)',
    url: 'https://www.earthdata.nasa.gov/data/instruments/modis',
    what: 'Sensor de los satélites Terra y Aqua; píxel de unos 1 km, serie desde 2000.',
  },
  osm: {
    name: 'OpenStreetMap',
    url: 'https://www.openstreetmap.org/copyright',
    what: 'Carreteras y núcleos de población para las vías de escape.',
  },
  maptiler: {
    name: 'MapTiler',
    url: 'https://www.maptiler.com/copyright/',
    what: 'Mapa base, relieve y curvas de nivel.',
  },
} satisfies Record<string, Source>;

const DAY = 86_400_000;

/** Días completos entre una fecha ISO (AAAA-MM-DD) y hoy. */
export function daysSince(iso: string, now = Date.now()): number {
  return Math.max(0, Math.floor((now - Date.parse(`${iso}T00:00:00Z`)) / DAY));
}

/** «hoy», «ayer» o «hace N días». */
export function ago(iso: string, now = Date.now()): string {
  const d = daysSince(iso, now);
  return d === 0 ? t('hoy') : d === 1 ? t('ayer') : t('hace {d} días', { d });
}

/** «2 nov» a partir de AAAA-MM-DD. */
export const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(locale(), {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });
