import { useT } from '../lib/i18n.ts';
import { Info } from 'lucide-react';
import { lazy, Suspense, useRef, useState } from 'react';
import { cn } from '../lib/cn.ts';
import { shortDate } from '../lib/sources.ts';
import { useHistory } from '../store/history.ts';
import { useUi } from '../store/ui.ts';

// La explicación solo se descarga al abrirla
const ProvenancePanel = lazy(() => import('./ProvenancePanel.tsx'));

/**
 * Chip único de procedencia, visible en cualquier ancho: qué es real (y de cuándo) y qué es
 * simulado. Resalta lo que está seleccionado y abre una explicación de cada capa con sus fuentes.
 */
export function Provenance() {
  const lastDate = useHistory((s) => s.manifest?.tiempo.ultimoDato);
  const incident = useUi((s) => s.selectedIncident);
  const [open, setOpen] = useState(false);
  const t = useT();
  const button = useRef<HTMLButtonElement>(null);

  // Lo seleccionado manda: un incendio real o, si no, la simulación activa
  const realFirst = !!incident;

  return (
    <>
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls="procedencia"
        onClick={() => setOpen(!open)}
        title={t('Qué es real y qué es simulado')}
        className="flex h-8 shrink-0 cursor-pointer items-center gap-0 overflow-hidden rounded-sm border border-line-strong text-xs font-semibold tracking-wide uppercase hover:bg-hover"
      >
        <span
          className={cn('flex h-full items-center gap-1.5 px-2 text-ok', realFirst && 'bg-ok/15')}
        >
          <span aria-hidden className="size-2.5 rounded-full bg-ok" />
          {/* En pantallas muy estrechas solo quedan las formas: el texto sigue para lectores */}
          <span className="max-[380px]:sr-only">{t('Real')}</span>
          {lastDate && (
            <span data-dinamico className="font-mono normal-case max-md:hidden">
              {shortDate(lastDate)}
            </span>
          )}
        </span>
        <span
          className={cn(
            'flex h-full items-center gap-1.5 border-l border-line-strong px-2 text-warn',
            !realFirst && 'bg-warn/15',
          )}
        >
          <span aria-hidden className="size-2.5 rotate-45 bg-warn" />
          <span className="max-md:sr-only">{t('Simulado')}</span>
          <span className="max-[380px]:hidden md:hidden" aria-hidden>
            {t('Sim.')}
          </span>
        </span>
        <Info
          size={14}
          strokeWidth={1.5}
          aria-hidden
          className="mx-1.5 text-ink-muted max-md:hidden"
        />
      </button>

      {open && (
        <Suspense fallback={null}>
          <ProvenancePanel trigger={button} onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  );
}
