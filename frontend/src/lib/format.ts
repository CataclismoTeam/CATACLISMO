// Formatos compartidos: idioma de la interfaz (español o inglés), UTC y unidades consistentes.
import { isEnglish, locale, t } from './i18n.ts';

const cache = new Map<string, Intl.NumberFormat>();
/** Formateador de números del idioma actual (se crea una vez por idioma y opciones). */
export function numberFormat(options: Intl.NumberFormatOptions = {}): Intl.NumberFormat {
  const key = locale() + JSON.stringify(options);
  let format = cache.get(key);
  if (!format) {
    format = new Intl.NumberFormat(locale(), options);
    cache.set(key, format);
  }
  return format;
}
// useGrouping 'always': el español no separa los millares de cuatro cifras por defecto
const integer = () => numberFormat({ maximumFractionDigits: 0, useGrouping: 'always' });
const oneDecimal = () => numberFormat({ maximumFractionDigits: 1 });

/** Número con hasta `digits` decimales en el idioma actual. */
export const formatNumber = (value: number, digits = 0) =>
  numberFormat({ maximumFractionDigits: digits, useGrouping: 'always' }).format(value);

export const MONTHS_SHORT = [
  'ene',
  'feb',
  'mar',
  'abr',
  'may',
  'jun',
  'jul',
  'ago',
  'sep',
  'oct',
  'nov',
  'dic',
] as const;

export const MONTHS_LONG = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
] as const;

const EN_SHORT = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];
const EN_LONG = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

/** Meses abreviados en el idioma actual. */
export const monthsShort = (): readonly string[] => (isEnglish() ? EN_SHORT : MONTHS_SHORT);
/** Nombre del mes (0 = enero) en el idioma actual. */
export const monthLong = (month: number): string =>
  isEnglish() ? EN_LONG[month] : MONTHS_LONG[month];

/** Conteos: enteros con separador de miles; los armonizados pequeños conservan un decimal. */
export function formatCount(value: number): string {
  if (!Number.isFinite(value)) return t('sin dato');
  return Math.abs(value) < 10 && !Number.isInteger(value)
    ? oneDecimal().format(value)
    : integer().format(Math.round(value));
}

export function formatSigned(value: number): string {
  const text = formatCount(Math.abs(value));
  if (text === '0') return '0';
  return `${value > 0 ? '+' : '−'}${text}`;
}

export function formatPercent(ratio: number): string {
  if (!Number.isFinite(ratio)) return t('sin referencia');
  const pct = Math.round(ratio * 100);
  // Con medianas casi nulas el porcentaje se dispara y deja de decir nada
  if (pct > 1000) return t('más de +1.000 %');
  return `${pct > 0 ? '+' : pct < 0 ? '−' : ''}${integer().format(Math.abs(pct))} %`;
}

export function formatArea(km2: number): string {
  return `${integer().format(Math.round(km2))} km²`;
}

/** «agosto de 2025» o «August 2025» */
export function formatMonth(year: number, month: number): string {
  return isEnglish() ? `${EN_LONG[month]} ${year}` : `${MONTHS_LONG[month]} de ${year}`;
}

export function slugify(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}
