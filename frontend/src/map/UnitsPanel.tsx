import { useT } from '../lib/i18n.ts';
import { Radio, X } from 'lucide-react';
import { useState } from 'react';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { Tag } from '../ui/Tag.tsx';
import { KIND, STATUS } from './markers.ts';
import { DOMAIN_LABEL, GROUPS, SCENARIOS, type Domain, type Unit } from './scenario.ts';

function UnitRow({ unit }: { unit: Unit }) {
  const selected = useUi((s) => s.selectedUnit === unit.id);
  const focusUnit = useUi((s) => s.focusUnit);
  const status = STATUS[unit.status];
  const t = useT();
  return (
    <li>
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => focusUnit(unit.id, [unit.lon, unit.lat])}
        className={cn(
          'flex w-full cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-sm pointer-coarse:min-h-11',
          selected ? 'border-accent bg-hover' : 'border-transparent hover:bg-hover',
        )}
      >
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="flex items-baseline gap-2">
            <strong className="font-mono">{unit.id}</strong>
            <span className="truncate text-ink-muted">{t(KIND[unit.kind].label)}</span>
          </span>
          <span className="text-xs" style={{ color: status.color }}>
            {t(status.label)}
          </span>
        </span>
      </button>
    </li>
  );
}

/** Panel izquierdo: medios del dispositivo por aire y tierra (en grupos). */
export function UnitsPanel() {
  const open = useUi((s) => s.leftPanel === 'unidades');
  const setLeftPanel = useUi((s) => s.setLeftPanel);
  const setRadioOpen = useUi((s) => s.setRadioOpen);
  const scenario = SCENARIOS[useUi((s) => s.scenario)];
  const [domain, setDomain] = useState<Domain>('tierra');
  const t = useT();
  if (!open || !scenario) return null;

  const of = (d: Domain) => scenario.units.filter((u) => u.domain === d);
  const domains: Domain[] = ['aire', 'tierra'];
  const current = domain;

  return (
    <aside
      aria-label={t('Unidades')}
      className="absolute inset-x-0 bottom-0 z-(--z-panel) flex max-h-[70%] flex-col rounded-t-lg border border-line-strong bg-surface shadow-panel md:inset-x-auto md:top-3 md:bottom-3 md:left-3 md:max-h-none md:w-80 md:rounded-lg"
    >
      <header className="flex items-center justify-between border-b border-line px-4 py-2">
        <div>
          <h2 className="m-0 text-base font-semibold">{t('Unidades')}</h2>
          <p className="m-0 text-xs text-ink-muted">{scenario.name}</p>
        </div>
        <div className="flex items-center gap-2">
          <Tag tone="simulado">{t('Simulado')}</Tag>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t('Cerrar unidades')}
            onClick={() => setLeftPanel(null)}
          >
            <X size={20} strokeWidth={1.5} aria-hidden />
          </Button>
        </div>
      </header>

      <div
        role="tablist"
        aria-label={t('Dominio')}
        className="grid grid-flow-col gap-1 border-b border-line p-2"
      >
        {domains.map((d, i) => (
          <button
            key={d}
            id={`pestana-${d}`}
            type="button"
            role="tab"
            aria-selected={current === d}
            aria-controls="panel-unidades"
            // Pestañas con tabulador itinerante: Tab entra en la activa y las flechas cambian
            tabIndex={current === d ? 0 : -1}
            onClick={() => setDomain(d)}
            onKeyDown={(e) => {
              if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
              e.preventDefault();
              const next =
                domains[(i + (e.key === 'ArrowRight' ? 1 : -1) + domains.length) % domains.length];
              setDomain(next);
              document.getElementById(`pestana-${next}`)?.focus();
            }}
            className={cn(
              'h-9 cursor-pointer rounded-md text-sm font-semibold pointer-coarse:h-11',
              current === d
                ? 'bg-accent text-on-accent'
                : 'text-ink-muted hover:bg-hover hover:text-ink',
            )}
          >
            {t(DOMAIN_LABEL[d])} ({of(d).length})
          </button>
        ))}
      </div>

      <div
        id="panel-unidades"
        role="tabpanel"
        aria-labelledby={`pestana-${current}`}
        tabIndex={0}
        className="min-h-0 flex-1 overflow-y-auto px-3 py-2"
      >
        {current === 'tierra' ? (
          <>
            <button
              type="button"
              onClick={() => setRadioOpen(true)}
              className="mb-2 flex w-full cursor-pointer items-center gap-2 rounded-md border border-line-strong px-3 py-2 text-left text-sm hover:bg-hover pointer-coarse:min-h-11"
            >
              <Radio size={16} strokeWidth={1.5} aria-hidden />
              <span className="flex-1">
                <strong>{t('Canal General Tierra')}</strong>
                <span className="block text-xs text-ink-muted">
                  {t('Hablan todos los medios de tierra ({n})', { n: of('tierra').length })}
                </span>
              </span>
            </button>
            {GROUPS.map((g) => {
              const list = of('tierra').filter((u) => u.group === g);
              return (
                <section key={g} className="mb-2">
                  <h3 className="m-0 flex items-center justify-between px-1 py-1 text-xs font-semibold tracking-wide text-ink-muted uppercase">
                    {t(g)}
                    <span className="flex items-center gap-1 font-normal normal-case">
                      <Radio size={12} strokeWidth={1.5} aria-hidden />
                      {t('canal propio')}
                    </span>
                  </h3>
                  <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                    {list.map((u) => (
                      <UnitRow key={u.id} unit={u} />
                    ))}
                  </ul>
                </section>
              );
            })}
          </>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
            {of(current).map((u) => (
              <UnitRow key={u.id} unit={u} />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
