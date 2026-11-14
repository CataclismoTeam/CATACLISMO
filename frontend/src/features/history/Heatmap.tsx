import { memo } from 'react';
import { cn } from '../../lib/cn.ts';
import { formatCount, formatMonth, MONTHS_SHORT } from '../../lib/format.ts';
import { UNIT, type CalendarModel } from './model.ts';
import { rampColor, rampGradient, scale } from './ramp.ts';
import type { MonthInfo } from './series.ts';

const MARK_PROVISIONAL = '*';
// Un mes incompleto tendrá al menos lo que ya lleva: se marca con ≥
const MARK_PARTIAL = '≥';

function describe(info: MonthInfo): string {
  const notes: string[] = [];
  if (info.state === 'parcial') {
    notes.push(`mes incompleto, ${info.daysCovered} de ${info.daysInMonth} días`);
  }
  if (info.provisional) notes.push('dato provisional');
  return notes.length ? `, ${notes.join(', ')}` : '';
}

const cellBase = 'h-7 min-w-11 px-1 text-right text-[0.8125rem] tabular-nums pointer-coarse:h-11';

interface Props {
  model: CalendarModel;
  onSelect: (mi: number) => void;
}

/** Calendario mes × año. Es una tabla real: se recorre con teclado y lector de pantalla. */
export const Heatmap = memo(function Heatmap({ model, onSelect }: Props) {
  const { values, infos, years, max, series } = model;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => formatCount(Math.round(t * t * max)));

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="overflow-x-auto">
        <table className="w-full border-separate border-spacing-0.5">
          <caption className="sr-only">
            Número de {UNIT[model.metric]} por mes y año. Pulsa un mes para compararlo con su
            mediana.
          </caption>
          <thead>
            <tr className="text-xs text-ink-muted">
              <th scope="col" className="w-12 text-left font-medium">
                Año
              </th>
              {MONTHS_SHORT.map((m) => (
                <th key={m} scope="col" className="font-medium">
                  {m}
                </th>
              ))}
              <th scope="col" className="pl-2 text-right font-medium">
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {years.map((year, yi) => (
              <tr key={year}>
                <th scope="row" className="text-left font-mono text-[0.8125rem] font-medium">
                  {year}
                </th>
                {MONTHS_SHORT.map((_, month) => {
                  const mi = (year - series.startYear) * 12 + month;
                  const info = infos[mi];
                  if (info.state === 'sin datos') {
                    return (
                      <td key={month} className={cn(cellBase, 'text-center text-ink-muted')}>
                        <span aria-hidden>–</span>
                        <span className="sr-only">sin datos</span>
                      </td>
                    );
                  }
                  const color = rampColor(scale(values[mi], max));
                  const active = mi === model.selected;
                  return (
                    <td key={month} className="p-0">
                      <button
                        type="button"
                        aria-pressed={active}
                        aria-label={`${formatMonth(year, month)}: ${formatCount(values[mi])}${describe(info)}`}
                        onClick={() => onSelect(mi)}
                        style={{ background: color.background, color: color.text }}
                        className={cn(
                          cellBase,
                          'block w-full cursor-pointer rounded-sm border-2 border-transparent hover:border-ink',
                          active && 'border-ink outline-2 outline-offset-1 outline-accent',
                          info.state === 'parcial' && 'border-dashed border-ink-muted',
                        )}
                      >
                        {info.state === 'parcial' && MARK_PARTIAL}
                        {formatCount(values[mi])}
                        {info.provisional && MARK_PROVISIONAL}
                      </button>
                    </td>
                  );
                })}
                <td className={cn(cellBase, 'pl-2 font-semibold')}>
                  {formatCount(model.yearTotals[yi])}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="text-ink-muted">
              <th scope="row" className="text-left text-xs font-medium">
                Mediana
              </th>
              {model.monthMedians.map((median, month) => (
                <td key={month} className={cellBase}>
                  {Number.isFinite(median) ? formatCount(median) : '–'}
                </td>
              ))}
              <td className={cn(cellBase, 'pl-2 font-semibold text-ink')}>
                {formatCount(model.total)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-muted">
        <div className="flex items-center gap-2">
          <span>Menos</span>
          <div className="w-48">
            <div
              className="h-3 rounded-sm border border-line-strong"
              style={{ background: rampGradient() }}
            />
            <div className="mt-0.5 flex justify-between font-mono">
              {ticks.map((tick, i) => (
                <span key={i}>{tick}</span>
              ))}
            </div>
          </div>
          <span>Más</span>
        </div>
        <span>Unidad: {UNIT[model.metric]} al mes</span>
        <span>
          {MARK_PROVISIONAL} provisional (casi tiempo real) · {MARK_PARTIAL} mes incompleto
        </span>
      </div>
    </div>
  );
});
