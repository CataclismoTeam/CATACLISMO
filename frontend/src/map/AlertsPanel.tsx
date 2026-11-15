import { locale, useT } from '../lib/i18n.ts';
import { Eye, OctagonAlert, TriangleAlert, X, type LucideIcon } from 'lucide-react';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { LoadError } from '../ui/LoadError.tsx';
import { Tag } from '../ui/Tag.tsx';
import { alertsFor, LEVEL, minutes, routeBbox, type AlertLevel } from './alerts.ts';
import { SCENARIOS, type Route } from './scenario.ts';

const ICON: Record<AlertLevel, LucideIcon> = {
  critico: OctagonAlert,
  alto: TriangleAlert,
  vigilancia: Eye,
};

/**
 * Panel izquierdo de avisos (SIMULADO): núcleos de población de la simulación activa ordenados
 * por la llegada del fuego, con su nivel según el margen de evacuación.
 */
export function AlertsPanel({
  routes,
  nucleos,
  loading,
  retry,
}: {
  routes: Route[];
  /** Núcleos de población con nombre en la zona analizada (OpenStreetMap) */
  nucleos?: number;
  loading: boolean;
  retry?: () => void;
}) {
  const open = useUi((s) => s.leftPanel === 'avisos');
  const setLeftPanel = useUi((s) => s.setLeftPanel);
  const scenario = SCENARIOS[useUi((s) => s.scenario)];
  const highlighted = useUi((s) => s.highlightRoute);
  const setHighlight = useUi((s) => s.setHighlightRoute);
  const flyTo = useUi((s) => s.flyTo);
  const t = useT();
  if (!open) return null;
  const alerts = alertsFor(routes);

  return (
    <aside
      aria-label={t('Avisos')}
      className="absolute inset-x-0 bottom-0 z-(--z-panel) flex max-h-[70%] flex-col rounded-t-lg border border-line-strong bg-surface shadow-panel md:inset-x-auto md:top-3 md:bottom-3 md:left-3 md:max-h-none md:w-80 md:rounded-lg"
    >
      <header className="flex items-center justify-between border-b border-line px-4 py-2">
        <div>
          <h2 className="m-0 text-base font-semibold">{t('Avisos')}</h2>
          <p className="m-0 text-xs text-ink-muted">{scenario?.name}</p>
        </div>
        <div className="flex items-center gap-2">
          <Tag tone="simulado">{t('Simulado')}</Tag>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t('Cerrar avisos')}
            onClick={() => setLeftPanel(null)}
          >
            <X size={20} strokeWidth={1.5} aria-hidden />
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        <p className="m-0 mb-2 px-1 text-xs text-ink-muted">
          {t(
            'Núcleos de población por orden de llegada del fuego. El nivel sale del margen entre la evacuación por la vía de escape y el fuego: crítico (menos de 30 min), alto (menos de 90) y vigilancia.',
          )}
        </p>
        {retry ? (
          <LoadError what="los avisos" onRetry={retry} />
        ) : loading ? (
          <p role="status" className="m-0 px-1 text-sm text-ink-muted">
            {t('Cargando avisos…')}
          </p>
        ) : alerts.length === 0 ? (
          <p className="m-0 px-1 text-sm">
            {t(
              'Sin avisos: el algoritmo no encontró núcleos de población amenazados en el área analizada',
            )}
            {nucleos ? ` (${t('{n} núcleos', { n: nucleos })})` : ''}.
          </p>
        ) : (
          <ol
            className="m-0 flex list-none flex-col gap-1.5 p-0"
            aria-label={t('Núcleos en riesgo')}
          >
            {alerts.map(({ route, level }) => {
              const Icon = ICON[level];
              const info = LEVEL[level];
              const active = highlighted === route.nombre;
              return (
                <li key={route.nombre}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      setHighlight(active ? undefined : route.nombre);
                      if (!active) flyTo(routeBbox(route));
                    }}
                    className={cn(
                      'flex w-full cursor-pointer gap-2.5 rounded-md border border-l-4 px-2.5 py-2 text-left text-sm pointer-coarse:min-h-11',
                      active ? 'border-accent bg-hover' : 'border-line hover:bg-hover',
                    )}
                    style={{ borderLeftColor: info.color }}
                  >
                    <Icon
                      size={18}
                      strokeWidth={1.75}
                      aria-hidden
                      className="mt-0.5 shrink-0"
                      style={{ color: info.color }}
                    />
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="flex items-baseline justify-between gap-2">
                        <strong className="truncate">{route.desde}</strong>
                        <span
                          className="shrink-0 text-xs font-semibold uppercase"
                          style={{ color: info.color }}
                        >
                          {t(info.label)}
                        </span>
                      </span>
                      <span className="text-xs">
                        {t('Fuego en')} <strong>{minutes(route.llegadaFuegoMin)}</strong>
                        {route.margenMin !== null
                          ? ` · ${t('margen {m}', { m: minutes(route.margenMin) })}`
                          : ` · ${t('sin ruta antes que el fuego')}`}
                      </span>
                      <span className="text-xs text-ink-muted">
                        {t('Evacuar a {r}: {d} km, {m}', {
                          r: route.refugio,
                          d: route.distanciaKm.toLocaleString(locale()),
                          m: minutes(route.tiempoMin),
                        })}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        )}
        {alerts.length > 0 && nucleos !== undefined && nucleos > alerts.length && (
          <p className="m-0 mt-2 px-1 text-xs text-ink-muted">
            {t(
              'De los {n} núcleos de la zona (OpenStreetMap), el algoritmo calcula la vía de escape de los primeros a los que llega el fuego (hasta 3).',
              { n: nucleos },
            )}
          </p>
        )}
      </div>
    </aside>
  );
}
