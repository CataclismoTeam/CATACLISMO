// Piezas comunes de la metodología (las usan la versión española y la inglesa).
import type { Manifest } from '../../data/types.ts';
import { t } from '../../lib/i18n.ts';
import { monthsShort } from '../../lib/format.ts';
import { decimal } from './methodData.ts';

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5 last:mb-0">
      <h3 className="m-0 mb-1.5 text-base font-semibold">{title}</h3>
      <div className="flex flex-col gap-2 text-sm">{children}</div>
    </section>
  );
}

/** Factor k de cada mes con su intervalo del 95 % (igual en los dos idiomas). */
export function FactorTable({ manifest }: { manifest: Manifest }) {
  const { metodo } = manifest;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-right text-[0.8125rem] tabular-nums">
        <caption className="mb-1 text-left text-ink-muted">
          {t('Factor k por mes del año e intervalo del 95 %')}
        </caption>
        <thead>
          <tr className="text-ink-muted">
            <th scope="row" className="text-left font-medium">
              {t('Mes')}
            </th>
            {monthsShort().map((m) => (
              <th key={m} scope="col" className="px-1 font-medium">
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row" className="text-left font-medium">
              k
            </th>
            {metodo.factores.map((k, i) => (
              <td key={i} className="px-1">
                {decimal().format(k)}
              </td>
            ))}
          </tr>
          <tr className="text-ink-muted">
            <th scope="row" className="text-left font-medium">
              {t('Mín.')}
            </th>
            {metodo.intervalo95.map(([lo], i) => (
              <td key={i} className="px-1">
                {decimal().format(lo)}
              </td>
            ))}
          </tr>
          <tr className="text-ink-muted">
            <th scope="row" className="text-left font-medium">
              {t('Máx.')}
            </th>
            {metodo.intervalo95.map(([, hi], i) => (
              <td key={i} className="px-1">
                {decimal().format(hi)}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export const P = ({ children }: { children: React.ReactNode }) => <p className="m-0">{children}</p>;
