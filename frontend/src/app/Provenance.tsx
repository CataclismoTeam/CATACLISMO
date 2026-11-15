import { ExternalLink, Info, X } from 'lucide-react';
import { useRef, useState } from 'react';
import { cn } from '../lib/cn.ts';
import { ago, shortDate, SOURCES, type Source } from '../lib/sources.ts';
import { usePopover } from '../lib/usePopover.ts';
import { SCENARIOS } from '../map/scenario.ts';
import { useHistory } from '../store/history.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';

export function SourceLink({ source, className }: { source: Source; className?: string }) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        'inline-flex items-center gap-1 text-accent underline-offset-2 hover:underline',
        className,
      )}
    >
      {source.name}
      <ExternalLink size={12} strokeWidth={1.5} aria-hidden />
      <span className="sr-only">(se abre en otra pestaña)</span>
    </a>
  );
}

/**
 * Chip único de procedencia, visible en cualquier ancho: qué es real (y de cuándo) y qué es
 * simulado. Resalta lo que está seleccionado y abre una explicación de cada capa con sus fuentes.
 */
export function Provenance() {
  const lastDate = useHistory((s) => s.manifest?.tiempo.ultimoDato);
  const incident = useUi((s) => s.selectedIncident);
  const scenario = SCENARIOS[useUi((s) => s.scenario)];
  const setMethodOpen = useUi((s) => s.setMethodOpen);
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  usePopover(open, () => setOpen(false), panel, button);

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
        title="Qué es real y qué es simulado"
        className="flex h-8 shrink-0 cursor-pointer items-center gap-0 overflow-hidden rounded-sm border border-line-strong text-xs font-semibold tracking-wide uppercase hover:bg-hover"
      >
        <span
          className={cn('flex h-full items-center gap-1.5 px-2 text-ok', realFirst && 'bg-ok/15')}
        >
          <span aria-hidden className="size-2.5 rounded-full bg-ok" />
          {/* En pantallas muy estrechas solo quedan las formas: el texto sigue para lectores */}
          <span className="max-[380px]:sr-only">Real</span>
          {lastDate && (
            <span data-dinamico className="font-mono normal-case max-sm:hidden">
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
          <span className="max-sm:sr-only">Simulado</span>
          <span className="max-[380px]:hidden sm:hidden" aria-hidden>
            Sim.
          </span>
        </span>
        <Info
          size={14}
          strokeWidth={1.5}
          aria-hidden
          className="mx-1.5 text-ink-muted max-sm:hidden"
        />
      </button>

      {open && (
        <div
          ref={panel}
          id="procedencia"
          role="dialog"
          aria-label="Procedencia de los datos"
          tabIndex={-1}
          className="absolute top-full right-3 left-3 z-(--z-overlay) mt-1 max-h-[calc(100dvh-5rem)] overflow-y-auto rounded-lg border border-line-strong bg-surface p-4 text-sm shadow-panel outline-none sm:left-auto sm:w-96"
        >
          <header className="mb-2 flex items-start justify-between gap-2">
            <h2 className="m-0 text-base font-semibold">Qué es real y qué es simulado</h2>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Cerrar procedencia"
              onClick={() => setOpen(false)}
            >
              <X size={20} strokeWidth={1.5} aria-hidden />
            </Button>
          </header>

          <section className="mb-3">
            <h3 className="m-0 mb-1 flex items-center gap-1.5 text-xs font-semibold tracking-wide text-ok uppercase">
              <span aria-hidden className="size-2.5 rounded-full bg-ok" />
              Real
            </h3>
            <p className="m-0">
              Incendios detectados y calendario histórico: focos de calor de los satélites{' '}
              <SourceLink source={SOURCES.viirs} /> y <SourceLink source={SOURCES.modis} />,
              servidos por <SourceLink source={SOURCES.firms} />.
            </p>
            {lastDate && (
              <p className="m-0 mt-1 text-ink-muted">
                Último dato: <span className="font-mono">{lastDate}</span> (
                <span data-dinamico>{ago(lastDate)}</span>). Los datos no se actualizan solos en
                esta demo.
              </p>
            )}
          </section>

          <section className="mb-3">
            <h3 className="m-0 mb-1 flex items-center gap-1.5 text-xs font-semibold tracking-wide text-warn uppercase">
              <span aria-hidden className="size-2.5 rotate-45 bg-warn" />
              Simulado
            </h3>
            <p className="m-0">
              {scenario ? <strong>{scenario.name}</strong> : 'La simulación activa'}: incendio,
              propagación prevista (modelo de demostración), unidades y radio. Las vías de escape
              son del algoritmo del equipo sobre carreteras de <SourceLink source={SOURCES.osm} />.
            </p>
          </section>

          <section className="mb-3">
            <h3 className="m-0 mb-1 text-xs font-semibold tracking-wide text-ink-muted uppercase">
              Ilustrativo
            </h3>
            <p className="m-0">
              El halo alrededor de los incendios reales activos usa un viento fijo de ejemplo: no es
              un pronóstico. Está apagado por defecto (panel Capas).
            </p>
          </section>

          <p className="m-0 border-t border-line pt-2 text-xs text-ink-muted">
            Cartografía: <SourceLink source={SOURCES.maptiler} /> ·{' '}
            <SourceLink source={SOURCES.osm} />.{' '}
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setMethodOpen(true);
              }}
              className="cursor-pointer text-accent underline-offset-2 hover:underline"
            >
              Datos y métodos
            </button>
          </p>
        </div>
      )}
    </>
  );
}
