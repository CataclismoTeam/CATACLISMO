import { ArrowUp, ChevronRight, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { cn } from '../lib/cn.ts';
import { formatCount } from '../lib/format.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { Tag } from '../ui/Tag.tsx';
import { byRegion, type Incident, type IncidentsFile } from './incidents.ts';
import { SCENARIO_LIST, type Route } from './scenario.ts';

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'];
const ALL = 'todas';
const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString('es-ES', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });

function Status({ active }: { active: boolean }) {
  // Forma + texto, no solo color
  return active ? (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-fire">
      <span aria-hidden className="size-2.5 rounded-full bg-fire" />
      Actividad reciente
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-xs text-ink-muted">
      <span aria-hidden className="size-2.5 rounded-full border-2 border-ink-muted" />
      Sin detecciones recientes
    </span>
  );
}

function IncidentRow({ incident }: { incident: Incident }) {
  const selected = useUi((s) => s.selectedIncident === incident.id);
  const focus = useUi((s) => s.focusIncident);
  const sameDay = incident.desde === incident.hasta;
  return (
    <li>
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => focus(incident.id, incident.bbox)}
        className={cn(
          'flex w-full cursor-pointer items-center gap-2 rounded-md border px-2.5 py-2 text-left text-sm pointer-coarse:min-h-11',
          selected ? 'border-accent bg-hover' : 'border-transparent hover:bg-hover',
        )}
      >
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex items-baseline justify-between gap-2">
            <strong className="truncate">{incident.provincia}</strong>
            <span className="shrink-0 font-mono text-xs text-ink-muted">
              {sameDay
                ? shortDate(incident.desde)
                : `${shortDate(incident.desde)} – ${shortDate(incident.hasta)}`}
            </span>
          </span>
          <span className="text-xs text-ink-muted">
            {formatCount(incident.detecciones)} detecciones ·{' '}
            {incident.areaKm2 < 1
              ? `${Math.round(incident.areaKm2 * 100)} ha`
              : `${formatCount(incident.areaKm2)} km²`}
          </span>
          <Status active={incident.activo} />
        </span>
        <ChevronRight size={16} strokeWidth={1.5} aria-hidden className="shrink-0 text-ink-muted" />
      </button>
    </li>
  );
}

/** Panel izquierdo: simulaciones y todos los incendios detectados, por comunidad autónoma. */
export function IncidentsPanel({
  incidents,
  routes,
}: {
  incidents?: IncidentsFile;
  routes: Route[];
}) {
  const open = useUi((s) => s.leftPanel === 'incendios');
  const setLeftPanel = useUi((s) => s.setLeftPanel);
  const setOpen = (next: boolean) => setLeftPanel(next ? 'incendios' : null);
  const scenarioId = useUi((s) => s.scenario);
  const setScenario = useUi((s) => s.setScenario);
  const [region, setRegion] = useState(ALL);
  const [onlyActive, setOnlyActive] = useState(false);

  const groups = useMemo(() => {
    if (!incidents) return [];
    return byRegion(incidents)
      .filter(([name]) => region === ALL || name === region)
      .map(([name, list]): [string, Incident[]] => [
        name,
        onlyActive ? list.filter((i) => i.activo) : list,
      ])
      .filter(([, list]) => list.length > 0);
  }, [incidents, region, onlyActive]);
  const shown = groups.reduce((n, [, list]) => n + list.length, 0);

  if (!open) return null;

  return (
    <aside
      aria-label="Incendios"
      className="absolute inset-x-0 bottom-0 z-(--z-panel) flex max-h-[70%] flex-col rounded-t-lg border border-line-strong bg-surface shadow-panel md:inset-x-auto md:top-3 md:bottom-3 md:left-3 md:max-h-none md:w-80 md:rounded-lg"
    >
      <header className="flex items-center justify-between border-b border-line px-4 py-2">
        <h2 className="m-0 text-base font-semibold">Incendios</h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Cerrar incendios"
          onClick={() => setOpen(false)}
        >
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <section className="border-b border-line px-4 py-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="m-0 text-xs font-semibold tracking-wide text-ink-muted uppercase">
              Simulaciones
            </h3>
            <Tag tone="simulado">Simulado</Tag>
          </div>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {SCENARIO_LIST.map((s) => {
              const active = s.id === scenarioId;
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => setScenario(s.id)}
                    className={cn(
                      'flex w-full cursor-pointer flex-col gap-1 rounded-md border px-2.5 py-2 text-left text-sm pointer-coarse:min-h-11',
                      active ? 'border-warn bg-hover' : 'border-transparent hover:bg-hover',
                    )}
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <strong>{s.name}</strong>
                      <span className="shrink-0 text-xs text-ink-muted">
                        {s.kind === 'urbano' ? 'Urbano-forestal' : 'Forestal'}
                      </span>
                    </span>
                    <span className="text-xs text-ink-muted">
                      {s.provincia} · {s.comunidad}
                    </span>
                    {active && (
                      <>
                        <span className="text-ink-muted">{s.description}</span>
                        <span className="flex items-center gap-1.5 text-xs">
                          <ArrowUp
                            size={14}
                            strokeWidth={2}
                            aria-hidden
                            style={{ transform: `rotate(${(s.windFrom + 180) % 360}deg)` }}
                          />
                          Viento del {COMPASS[Math.round(s.windFrom / 45) % 8]}, {s.windKmh} km/h
                        </span>
                        {routes.length === 0 && (
                          <span className="mt-1 border-t border-line pt-1.5 text-xs text-ink-muted">
                            Sin vías de escape calculadas: el algoritmo no encontró núcleos de
                            población amenazados en el área analizada.
                          </span>
                        )}
                        {routes.length > 0 && (
                          <span className="mt-1 flex flex-col gap-1 border-t border-line pt-1.5">
                            <span className="text-xs font-semibold">Vías de escape</span>
                            {routes.map((r) => (
                              <span key={r.nombre} className="text-xs">
                                <span className="text-ink">{r.nombre}</span>
                                <span className="block text-ink-muted">
                                  {r.distanciaKm.toLocaleString('es-ES')} km · {r.tiempoMin} min
                                  {r.margenMin !== null &&
                                    ` · margen con el fuego ${r.margenMin} min`}
                                </span>
                              </span>
                            ))}
                          </span>
                        )}
                      </>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="px-4 py-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="m-0 text-xs font-semibold tracking-wide text-ink-muted uppercase">
              Detectados por satélite
            </h3>
            <Tag tone="real">Real · FIRMS</Tag>
          </div>
          {!incidents ? (
            <p role="status" className="m-0 text-sm text-ink-muted">
              Cargando incendios…
            </p>
          ) : (
            <>
              <p className="m-0 mb-2 text-xs text-ink-muted">
                Del {shortDate(incidents.desde)} al {shortDate(incidents.hasta)}: grupos de 3 o más
                detecciones a menos de 2 km y 3 días entre sí.
              </p>
              <label className="mb-2 flex flex-col gap-1 text-sm">
                <span className="text-ink-muted">Comunidad autónoma</span>
                <select
                  value={region}
                  onChange={(e) => setRegion(e.target.value)}
                  className="h-9 rounded-md border border-line-strong bg-canvas px-2 text-sm text-ink pointer-coarse:h-11"
                >
                  <option value={ALL}>Todas ({incidents.incendios.length})</option>
                  {byRegion(incidents).map(([name, list]) => (
                    <option key={name} value={name}>
                      {name} ({list.length})
                    </option>
                  ))}
                </select>
              </label>
              <label className="mb-3 flex items-center gap-2 text-sm pointer-coarse:min-h-11">
                <input
                  type="checkbox"
                  checked={onlyActive}
                  onChange={(e) => setOnlyActive(e.target.checked)}
                  className="size-4 accent-accent"
                />
                Solo con actividad reciente
              </label>
              {shown === 0 ? (
                <p className="m-0 text-sm">
                  Ningún incendio con actividad reciente en esta selección. Quita el filtro o elige
                  otra comunidad.
                </p>
              ) : (
                groups.map(([name, list]) => (
                  <details key={name} open={region !== ALL || groups.length <= 3} className="mb-1">
                    <summary className="flex cursor-pointer items-center justify-between rounded-md px-1 py-1.5 text-sm font-semibold hover:bg-hover pointer-coarse:min-h-11">
                      {name}
                      <span className="font-mono text-xs font-normal text-ink-muted">
                        {list.length}
                      </span>
                    </summary>
                    <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                      {list.map((i) => (
                        <IncidentRow key={i.id} incident={i} />
                      ))}
                    </ul>
                  </details>
                ))
              )}
            </>
          )}
        </section>
      </div>
    </aside>
  );
}
