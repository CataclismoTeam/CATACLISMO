// Formatos compartidos: español, UTC y unidades consistentes en toda la interfaz.
// useGrouping 'always': el español no separa los millares de cuatro cifras por defecto
const integer = new Intl.NumberFormat('es-ES', {
  maximumFractionDigits: 0,
  useGrouping: 'always',
});
const oneDecimal = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 });

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

/** Conteos: enteros con separador de miles; los armonizados pequeños conservan un decimal. */
export function formatCount(value: number): string {
  if (!Number.isFinite(value)) return 'sin dato';
  return Math.abs(value) < 10 && !Number.isInteger(value)
    ? oneDecimal.format(value)
    : integer.format(Math.round(value));
}

export function formatSigned(value: number): string {
  const text = formatCount(Math.abs(value));
  if (text === '0') return '0';
  return `${value > 0 ? '+' : '−'}${text}`;
}

export function formatPercent(ratio: number): string {
  if (!Number.isFinite(ratio)) return 'sin referencia';
  const pct = Math.round(ratio * 100);
  // Con medianas casi nulas el porcentaje se dispara y deja de decir nada
  if (pct > 1000) return 'más de +1.000 %';
  return `${pct > 0 ? '+' : pct < 0 ? '−' : ''}${integer.format(Math.abs(pct))} %`;
}

export function formatArea(km2: number): string {
  return `${integer.format(Math.round(km2))} km²`;
}

/** "agosto de 2025" */
export function formatMonth(year: number, month: number): string {
  return `${MONTHS_LONG[month]} de ${year}`;
}

export function slugify(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}
