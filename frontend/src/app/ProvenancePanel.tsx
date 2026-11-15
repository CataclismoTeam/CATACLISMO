import { X } from 'lucide-react';
import { useRef, type RefObject } from 'react';
import { ago, SOURCES } from '../lib/sources.ts';
import { usePopover } from '../lib/usePopover.ts';
import { SCENARIOS } from '../map/scenario.ts';
import { useHistory } from '../store/history.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { SourceLink } from '../ui/SourceLink.tsx';

/** Explicación de qué es real y qué es simulado, con las fuentes de cada capa. */
export default function ProvenancePanel({
  trigger,
  onClose,
}: {
  trigger: RefObject<HTMLButtonElement | null>;
  onClose: () => void;
}) {
  const lastDate = useHistory((s) => s.manifest?.tiempo.ultimoDato);
  const scenario = SCENARIOS[useUi((s) => s.scenario)];
  const setMethodOpen = useUi((s) => s.setMethodOpen);
  const panel = useRef<HTMLDivElement>(null);
  usePopover(true, onClose, panel, trigger);

  return (
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
        <Button variant="ghost" size="icon" aria-label="Cerrar procedencia" onClick={onClose}>
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
          <SourceLink source={SOURCES.viirs} /> y <SourceLink source={SOURCES.modis} />, servidos
          por <SourceLink source={SOURCES.firms} />.
        </p>
        {lastDate && (
          <p className="m-0 mt-1 text-ink-muted">
            Último dato: <span className="font-mono">{lastDate}</span> (
            <span data-dinamico>{ago(lastDate)}</span>). Los datos no se actualizan solos en esta
            demo.
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
          propagación prevista (modelo de demostración), unidades y radio. Las vías de escape son
          del algoritmo del equipo sobre carreteras de <SourceLink source={SOURCES.osm} />.
        </p>
      </section>

      <section className="mb-3">
        <h3 className="m-0 mb-1 text-xs font-semibold tracking-wide text-ink-muted uppercase">
          Ilustrativo
        </h3>
        <p className="m-0">
          El halo alrededor de los incendios reales activos usa un viento fijo de ejemplo: no es un
          pronóstico. Está apagado por defecto (panel Capas).
        </p>
      </section>

      <p className="m-0 border-t border-line pt-2 text-xs text-ink-muted">
        Cartografía: <SourceLink source={SOURCES.maptiler} /> · <SourceLink source={SOURCES.osm} />.{' '}
        <button
          type="button"
          onClick={() => {
            onClose();
            setMethodOpen(true);
          }}
          className="cursor-pointer text-accent underline-offset-2 hover:underline"
        >
          Datos y métodos
        </button>
      </p>
    </div>
  );
}
