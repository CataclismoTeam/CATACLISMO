// Exportación CSV conforme a RFC 4180: UTF-8 con BOM (Excel), coma, punto decimal,
// CRLF y fechas ISO 8601. Los metadatos van en columnas para no romper el formato.
import type { Manifest } from '../../data/types.ts';
import { slugify } from '../../lib/format.ts';
import { describeArea, type Area } from './area.ts';
import { monthInfo, type Series } from './series.ts';

const COLUMNS = [
  'fecha',
  'anio',
  'mes',
  'sensor_origen',
  'conteo_bruto_modis',
  'conteo_bruto_viirs',
  'conteo_armonizado',
  'factor_viirs_a_modis',
  'frp_modis_mw',
  'frp_viirs_mw',
  'dias_con_datos',
  'dias_del_mes',
  'provisional',
  'area',
  'metodo',
  'version_datos',
  'fuente',
] as const;

function escapeField(value: string | number): string {
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

const fixed = (value: number, digits: number) =>
  Number.isFinite(value) ? String(Number(value.toFixed(digits))) : '';

export function buildCsv(
  series: Series,
  manifest: Manifest,
  area: Area,
  yearRange: [number, number],
): string {
  const lines = [COLUMNS.join(',')];
  const version = `v${manifest.version} (${manifest.generado})`;
  for (let mi = 0; mi < series.h.length; mi++) {
    const year = series.startYear + Math.floor(mi / 12);
    const month = mi % 12;
    const info = monthInfo(manifest, mi);
    if (year < yearRange[0] || year > yearRange[1] || info.state === 'sin datos') continue;
    const row: (string | number)[] = [
      `${year}-${String(month + 1).padStart(2, '0')}-01`,
      year,
      month + 1,
      info.sensors,
      series.m[mi],
      series.v[mi],
      fixed(series.h[mi], 2),
      manifest.metodo.factores[month],
      fixed(series.frpM[mi], 1),
      fixed(series.frpV[mi], 1),
      info.daysCovered,
      info.daysInMonth,
      info.provisional ? 'si' : 'no',
      describeArea(area),
      manifest.metodo.nombre,
      version,
      'NASA FIRMS (MODIS C6.1 y VIIRS S-NPP C2)',
    ];
    lines.push(row.map(escapeField).join(','));
  }
  return `﻿${lines.join('\r\n')}\r\n`;
}

export function csvFileName(area: Area, yearRange: [number, number]): string {
  return `cataclismo-fuego_${slugify(area.name) || 'area'}_${yearRange[0]}-${yearRange[1]}.csv`;
}

export function download(
  name: string,
  content: Blob | string,
  type = 'text/csv;charset=utf-8',
): void {
  const blob = typeof content === 'string' ? new Blob([content], { type }) : content;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
