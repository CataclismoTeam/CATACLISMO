import { Maximize2, Minimize2, Pause, Play } from 'lucide-react';
import { lazy, Suspense, useEffect, useState } from 'react';
import { ErrorBoundary } from '../../app/ErrorBoundary.tsx';
import { cn } from '../../lib/cn.ts';
import { formatMonth } from '../../lib/format.ts';
import { useHistory } from '../../store/history.ts';
import { useUi } from '../../store/ui.ts';
import { Button } from '../../ui/Button.tsx';
import { Tag } from '../../ui/Tag.tsx';
import { AnomalyBadge } from './AnomalyBadge.tsx';
import { useCalendarModel } from './model.ts';

const CalendarPanel = lazy(() => import('./CalendarPanel.tsx'));

function Skeleton() {
  return (
    <div role="status" className="flex flex-col gap-2 p-4">
      <span className="sr-only">Cargando el calendario…</span>
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="h-7 animate-pulse rounded-sm bg-raised" />
      ))}
    </div>
  );
}

/** Panel inferior ampliable con el calendario de actividad de fuego. */
export function CalendarDock() {
  const open = useUi((s) => s.calendarOpen);
  const setOpen = useUi((s) => s.setCalendarOpen);
  const status = useHistory((s) => s.status);
  const gridStatus = useHistory((s) => s.gridStatus);
  const error = useHistory((s) => s.error);
  const load = useHistory((s) => s.load);
  const areaName = useHistory((s) => s.area.name);
  const model = useCalendarModel();
  const failed = status === 'error' || (gridStatus === 'error' && !model);
  const selected = useHistory((s) => s.selected);
  const select = useHistory((s) => s.select);
  const manifest = useHistory((s) => s.manifest);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);

  useEffect(() => {
    if (!playing || !manifest) return;
    const id = window.setInterval(() => {
      const last = manifest.tiempo.meses - 1;
      const next = selected >= last ? 0 : selected + 1;
      select(next);
    }, 1200 / speed);
    return () => window.clearInterval(id);
  }, [manifest, playing, select, selected, speed]);

  return (
    <section
      aria-labelledby="calendario-titulo"
      className={cn(
        'z-(--z-panel) flex shrink-0 flex-col border-t border-line bg-surface',
        open && 'h-[76dvh] md:h-[min(72dvh,43rem)]',
      )}
    >
      <header className="flex min-h-14 shrink-0 items-center gap-3 border-b border-line px-4">
        <div className="min-w-0">
          <p className="m-0 text-[10px] font-semibold uppercase tracking-[0.18em] text-accent">
            Análisis histórico
          </p>
          <h2 id="calendario-titulo" className="m-0 truncate text-sm font-semibold">
            Actividad de fuego <span className="font-normal text-ink-muted">/ {areaName}</span>
          </h2>
        </div>
        {model && !open && (
          <span className="hidden items-center gap-2 text-sm sm:flex">
            <span className="first-letter:uppercase">
              {formatMonth(model.selectedYear, model.selectedMonth)}
            </span>
            <AnomalyBadge level={model.anomaly.level} />
          </span>
        )}
        <Tag tone="real" className="ml-auto hidden lg:inline-flex">
          Real · MODIS + VIIRS
        </Tag>
        {model && manifest && (
          <div className="hidden items-center gap-1 xl:flex" aria-label="Línea de tiempo">
            <Button
              variant="ghost"
              size="icon"
              aria-label={playing ? 'Pausar línea de tiempo' : 'Reproducir línea de tiempo'}
              aria-pressed={playing}
              onClick={() => setPlaying(!playing)}
            >
              {playing ? <Pause size={16} aria-hidden /> : <Play size={16} aria-hidden />}
            </Button>
            <input
              className="w-32 accent-accent"
              type="range"
              min={0}
              max={manifest.tiempo.meses - 1}
              value={selected}
              onChange={(event) => select(Number(event.target.value))}
              aria-label="Mes de la línea de tiempo"
            />
            <select
              className="h-8 rounded-md border border-line-strong bg-canvas px-1 text-xs"
              value={speed}
              onChange={(event) => setSpeed(Number(event.target.value))}
              aria-label="Velocidad de reproducción"
            >
              <option value={0.5}>0,5×</option>
              <option value={1}>1×</option>
              <option value={2}>2×</option>
            </select>
          </div>
        )}
        <Button
          variant="ghost"
          className="ml-auto lg:ml-0"
          aria-expanded={open}
          aria-controls="calendario-contenido"
          onClick={() => setOpen(!open)}
        >
          {open ? (
            <Minimize2 size={20} strokeWidth={1.5} aria-hidden />
          ) : (
            <Maximize2 size={20} strokeWidth={1.5} aria-hidden />
          )}
          {open ? 'Minimizar' : 'Maximizar'}
        </Button>
      </header>

      {open && (
        <div id="calendario-contenido" className="min-h-0 flex-1 overflow-y-auto">
          {failed ? (
            <div role="alert" className="flex flex-col items-center gap-3 p-8 text-center">
              <p className="m-0 text-base">
                No se pudieron cargar los datos de fuego. {error} Comprueba la conexión y vuelve a
                intentarlo.
              </p>
              <Button variant="primary" onClick={() => void load()}>
                Reintentar
              </Button>
            </div>
          ) : model ? (
            <ErrorBoundary what="el calendario">
              <Suspense fallback={<Skeleton />}>
                <CalendarPanel model={model} />
              </Suspense>
            </ErrorBoundary>
          ) : (
            <Skeleton />
          )}
        </div>
      )}
    </section>
  );
}
