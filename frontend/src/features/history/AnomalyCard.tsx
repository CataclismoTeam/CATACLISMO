import { TriangleAlert } from 'lucide-react';
import {
  formatCount,
  formatMonth,
  formatPercent,
  formatSigned,
  MONTHS_LONG,
} from '../../lib/format.ts';
import { Button } from '../../ui/Button.tsx';
import { AnomalyBadge } from './AnomalyBadge.tsx';
import { UNIT, type CalendarModel } from './model.ts';
import { lastCompleteMonth } from './series.ts';
import { MIN_REFERENCE_YEARS } from './stats.ts';

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <p className="m-0 flex gap-2 rounded-md border border-warn/60 bg-canvas p-2.5 text-sm">
      <TriangleAlert size={16} strokeWidth={2} className="mt-0.5 shrink-0 text-warn" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

/** Mes seleccionado frente a la mediana de ese mismo mes en los demás años. */
export function AnomalyCard({
  model,
  onSelect,
}: {
  model: CalendarModel;
  onSelect: (mi: number) => void;
}) {
  const { reference: ref, anomaly, info, value, selectedYear, selectedMonth } = model;
  const monthName = MONTHS_LONG[selectedMonth];
  const complete = lastCompleteMonth(model.manifest);
  const completeYear = model.series.startYear + Math.floor(complete / 12);
  const enough = ref.values.length >= MIN_REFERENCE_YEARS;

  return (
    <section aria-labelledby="anomalia-titulo" className="flex flex-col gap-3">
      <h3 id="anomalia-titulo" className="m-0 text-base font-semibold first-letter:uppercase">
        {formatMonth(selectedYear, selectedMonth)}
      </h3>

      <div className="flex flex-wrap items-end gap-x-4 gap-y-2" aria-live="polite">
        <p className="m-0 leading-none">
          <span className="text-3xl font-semibold tabular-nums">{formatCount(value)}</span>
          <span className="ml-2 text-sm text-ink-muted">{UNIT[model.metric]}</span>
        </p>
        <AnomalyBadge level={anomaly.level} large />
      </div>

      {enough ? (
        <p className="m-0 text-sm">
          <strong className="tabular-nums">{formatPercent(anomaly.ratio)}</strong> respecto a la
          mediana ({formatSigned(anomaly.difference)} detecciones). Mediana de {monthName}:{' '}
          <strong className="tabular-nums">{formatCount(ref.median)}</strong>; lo habitual va de{' '}
          {formatCount(ref.p25)} a {formatCount(ref.p75)}.
        </p>
      ) : (
        <p className="m-0 text-sm">
          Solo hay {ref.values.length} años completos de {monthName} para comparar y hacen falta{' '}
          {MIN_REFERENCE_YEARS}. Amplía el rango de años.
        </p>
      )}
      {enough && (
        <p className="m-0 text-xs text-ink-muted">
          Referencia: {monthName} de {ref.years.length} años completos entre {model.yearRange[0]} y{' '}
          {model.yearRange[1]}, sin contar {selectedYear}.
        </p>
      )}

      {info.state === 'parcial' && (
        <Notice>
          Mes incompleto: hay datos de {info.daysCovered} de {info.daysInMonth} días. Se compara con
          meses enteros, así que todavía sale más bajo de lo que será.
          {complete !== model.selected && (
            <Button className="mt-2 flex" onClick={() => onSelect(complete)}>
              Ver {formatMonth(completeYear, complete % 12)}, último mes completo
            </Button>
          )}
        </Notice>
      )}
      {info.provisional && (
        <Notice>
          Dato provisional: incluye detecciones en casi tiempo real que pueden cambiar cuando NASA
          publique el procesado definitivo.
        </Notice>
      )}
    </section>
  );
}
