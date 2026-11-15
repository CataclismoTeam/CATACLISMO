// Imagen PNG del calendario (y del gráfico del mes, si está cargado), dibujada en un canvas
// propio para que salga igual en cualquier pantalla e incluya área, unidad y atribución.
import { t } from '../../lib/i18n.ts';
import { formatCount, formatMonth, monthsShort, slugify } from '../../lib/format.ts';
import { describeArea, type Area } from './area.ts';
import { chartImage } from './chartHandle.ts';
import { UNIT, type CalendarModel } from './model.ts';
import { rampColor, scale } from './ramp.ts';
import { METRIC_LABEL } from './series.ts';

const W = 1280;
const PAD = 32;
const CELL_H = 30;
const YEAR_W = 64;
const TOTAL_W = 96;
const CHART_H = 300;
const BG = '#12171e';
const INK = '#e9edf3';
const MUTED = '#a6b1c0';
const FONT = '"Inter Variable", system-ui, sans-serif';

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('imagen no válida'));
    img.src = src;
  });
}

export async function calendarPng(model: CalendarModel, area: Area): Promise<Blob> {
  const { years, values, infos, max, series } = model;
  const chartSrc = chartImage();
  const tableTop = 112;
  const tableH = (years.length + 1) * CELL_H;
  const chartTop = tableTop + tableH + 64;
  const H = (chartSrc ? chartTop + CHART_H : tableTop + tableH) + 72;

  const canvas = document.createElement('canvas');
  canvas.width = W * 2;
  canvas.height = H * 2;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('canvas no disponible');
  ctx.scale(2, 2);
  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, W, H);
  ctx.textBaseline = 'middle';

  const text = (
    value: string,
    x: number,
    y: number,
    style: string,
    color = INK,
    align: CanvasTextAlign = 'left',
  ) => {
    ctx.font = `${style} ${FONT}`;
    ctx.fillStyle = color;
    ctx.textAlign = align;
    ctx.fillText(value, x, y);
  };

  text(`CATACLISMO · ${t('Calendario de actividad de fuego')}`, PAD, 36, '600 22px');
  text(
    `${describeArea(area)} · ${t(METRIC_LABEL[model.metric])} (${t(UNIT[model.metric])}) · ${model.yearRange[0]}–${model.yearRange[1]}`,
    PAD,
    66,
    '400 14px',
    MUTED,
  );

  const cellW = (W - PAD * 2 - YEAR_W - TOTAL_W) / 12;
  monthsShort().forEach((m, i) =>
    text(m, PAD + YEAR_W + cellW * (i + 0.5), tableTop - 14, '500 13px', MUTED, 'center'),
  );
  text(t('Total'), W - PAD, tableTop - 14, '500 13px', MUTED, 'right');

  years.forEach((year, yi) => {
    const y = tableTop + yi * CELL_H;
    text(String(year), PAD, y + CELL_H / 2, '500 13px');
    for (let month = 0; month < 12; month++) {
      const mi = (year - series.startYear) * 12 + month;
      const x = PAD + YEAR_W + cellW * month;
      const info = infos[mi];
      if (info.state === 'sin datos') {
        text('–', x + cellW / 2, y + CELL_H / 2, '400 13px', MUTED, 'center');
        continue;
      }
      const color = rampColor(scale(values[mi], max));
      ctx.fillStyle = color.background;
      ctx.fillRect(x + 1, y + 1, cellW - 2, CELL_H - 2);
      if (mi === model.selected) {
        ctx.strokeStyle = INK;
        ctx.lineWidth = 2;
        ctx.strokeRect(x + 2, y + 2, cellW - 4, CELL_H - 4);
      }
      const label = `${info.state === 'parcial' ? '≥' : ''}${formatCount(values[mi])}${info.provisional ? '*' : ''}`;
      text(label, x + cellW - 8, y + CELL_H / 2, '500 13px', color.text, 'right');
    }
    text(formatCount(model.yearTotals[yi]), W - PAD, y + CELL_H / 2, '600 13px', INK, 'right');
  });

  const medianY = tableTop + years.length * CELL_H + CELL_H / 2;
  text(t('Mediana'), PAD, medianY, '500 12px', MUTED);
  model.monthMedians.forEach((median, month) =>
    text(
      Number.isFinite(median) ? formatCount(median) : '–',
      PAD + YEAR_W + cellW * (month + 1) - 8,
      medianY,
      '400 13px',
      MUTED,
      'right',
    ),
  );

  if (chartSrc) {
    text(
      t('{mes} frente a los demás años · mediana {m}', {
        mes: formatMonth(model.selectedYear, model.selectedMonth),
        m: formatCount(model.reference.median),
      }),
      PAD,
      chartTop - 20,
      '600 15px',
    );
    ctx.drawImage(await loadImage(chartSrc), PAD, chartTop, W - PAD * 2, CHART_H);
  }

  text(
    t(
      '* provisional (casi tiempo real) · ≥ mes incompleto · Fuente: NASA FIRMS (MODIS C6.1 y VIIRS S-NPP C2), datos hasta {d}',
      { d: model.manifest.tiempo.ultimoDato },
    ),
    PAD,
    H - 44,
    '400 12px',
    MUTED,
  );
  text(
    t('Método: {m}. NASA no avala este producto.', { m: model.manifest.metodo.nombre }),
    PAD,
    H - 24,
    '400 12px',
    MUTED,
  );

  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('no se pudo crear el PNG'))),
      'image/png',
    ),
  );
}

export function pngFileName(area: Area, yearRange: [number, number]): string {
  return `cataclismo-fuego_${slugify(area.name) || 'area'}_${yearRange[0]}-${yearRange[1]}.png`;
}
