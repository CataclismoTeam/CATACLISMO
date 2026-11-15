import { useT } from '../lib/i18n.ts';
import { Eye, EyeOff, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn.ts';
import { useUi, type Basemap, type LayerId } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import type { Detections } from './detections.ts';
import type { Remote } from './useRemote.ts';
import {
  ACTIVE_COLOR,
  AREA_COLOR,
  HALO_COLOR,
  MONTH_RAMP,
  PREDICTION_BANDS,
  type Pattern,
} from './overlays.ts';
import { provider } from './providers.ts';

const BASEMAPS: [Basemap, string][] = [
  ['satelite', 'Satélite'],
  ['topografico', 'Topográfico'],
];

type Origin = 'real' | 'simulado' | 'modelo' | 'ilustrativa';
const ORIGIN: Record<Origin, { label: string; className: string }> = {
  real: { label: 'Real', className: 'border-ok/60 text-ok' },
  simulado: { label: 'Simulado', className: 'border-warn/60 text-warn' },
  modelo: { label: 'Predicción', className: 'border-water/60 text-water' },
  ilustrativa: { label: 'Ilustrativa', className: 'border-line-strong text-ink-muted' },
};

function Toggle({
  id,
  label,
  origin,
  legend,
  disabled,
}: {
  id: LayerId;
  label: string;
  origin?: Origin;
  legend?: ReactNode;
  disabled?: string;
}) {
  const on = useUi((s) => s.layers[id]);
  const toggle = useUi((s) => s.toggleLayer);
  const t = useT();
  return (
    <li className="border-t border-line py-2 first:border-t-0">
      <button
        type="button"
        aria-pressed={on}
        disabled={!!disabled}
        title={disabled && t(disabled)}
        onClick={() => toggle(id)}
        className="flex min-h-9 w-full cursor-pointer items-center gap-2 rounded-sm text-left text-sm disabled:cursor-not-allowed disabled:opacity-50 pointer-coarse:min-h-11"
      >
        {on ? (
          <Eye size={16} strokeWidth={1.5} aria-hidden className="shrink-0 text-accent" />
        ) : (
          <EyeOff size={16} strokeWidth={1.5} aria-hidden className="shrink-0 text-ink-muted" />
        )}
        <span className={cn('flex-1', !on && 'text-ink-muted')}>{t(label)}</span>
        {origin && (
          <span
            className={cn(
              'rounded-sm border px-1.5 text-xs font-semibold uppercase',
              ORIGIN[origin].className,
            )}
          >
            {t(ORIGIN[origin].label)}
          </span>
        )}
      </button>
      {disabled && <p className="m-0 mt-1 pl-6 text-xs text-ink-muted">{t(disabled)}</p>}
      {on && legend && <div className="mt-1.5 pl-6">{legend}</div>}
    </li>
  );
}

const stripes = (fill: string, deg: number) =>
  `repeating-linear-gradient(${deg}deg, ${fill} 0 2px, transparent 2px 6px)`;
/** La misma trama que en el mapa: «/», «\\» o cruzada */
const PATTERN_CSS: Record<Pattern, (fill: string) => string> = {
  '/': (fill) => stripes(fill, 135),
  '\\': (fill) => stripes(fill, 45),
  x: (fill) => `${stripes(fill, 135)}, ${stripes(fill, 45)}`,
};

function Swatch({ fill, hatch, children }: { fill: string; hatch?: Pattern; children: ReactNode }) {
  const t = useT();
  return (
    <span className="flex items-center gap-2 text-xs">
      <span
        aria-hidden
        className="size-3.5 shrink-0 rounded-[2px] border border-line-strong"
        style={{
          background: hatch ? PATTERN_CSS[hatch](fill) : fill,
        }}
      />
      {typeof children === 'string' ? t(children) : children}
    </span>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  const t = useT();
  return (
    <section className="border-t border-line px-4 py-3">
      <h3 className="m-0 mb-1 text-xs font-semibold tracking-wide text-ink-muted uppercase">
        {t(title)}
      </h3>
      <ul className="m-0 list-none p-0">{children}</ul>
    </section>
  );
}

/** Panel de capas: mapa base, relieve y capas agrupadas con su origen y su leyenda. */
export function LayersPanel({ detections: load }: { detections: Remote<Detections> }) {
  const detections = load.status === 'listo' ? load.data : undefined;
  const open = useUi((s) => s.layersOpen);
  const setOpen = useUi((s) => s.setLayersOpen);
  const basemap = useUi((s) => s.basemap);
  const setBasemap = useUi((s) => s.setBasemap);
  const mode = useUi((s) => s.mapMode);
  const exaggeration = useUi((s) => s.exaggeration);
  const setExaggeration = useUi((s) => s.setExaggeration);
  const t = useT();

  if (!open) return null;

  return (
    <aside
      aria-label={t('Capas del mapa')}
      // Esc cierra el panel y devuelve el foco a su botón (no se cierra al pulsar el mapa:
      // se usa a la vez que el mapa)
      onKeyDown={(e) => {
        if (e.key !== 'Escape') return;
        e.stopPropagation();
        setOpen(false);
        document.querySelector<HTMLElement>('[data-abre="capas"]')?.focus();
      }}
      className="overflow-y-auto border border-line-strong bg-surface shadow-panel max-md:absolute max-md:inset-x-0 max-md:bottom-0 max-md:z-(--z-panel) max-md:max-h-[70%] max-md:rounded-t-lg md:min-h-0 md:w-80 md:rounded-lg"
    >
      <header className="sticky top-0 flex items-center justify-between bg-surface px-4 py-2">
        <h2 className="m-0 text-base font-semibold">{t('Capas')}</h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t('Cerrar capas')}
          onClick={() => setOpen(false)}
        >
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>

      <section className="px-4 pb-3">
        <h3 className="m-0 mb-1.5 text-xs font-semibold tracking-wide text-ink-muted uppercase">
          {t('Mapa base')}
        </h3>
        <div role="radiogroup" aria-label={t('Mapa base')} className="grid grid-cols-2 gap-1">
          {BASEMAPS.map(([id, label]) => (
            <Button
              key={id}
              role="radio"
              aria-checked={basemap === id}
              className={cn('px-2', basemap === id && 'border-accent bg-hover')}
              onClick={() => setBasemap(id)}
            >
              {t(label)}
            </Button>
          ))}
        </div>
        {mode === '3d' && (
          <label className="mt-3 flex flex-col gap-1 text-sm">
            <span className="flex justify-between">
              {t('Exageración del relieve')}
              <span className="font-mono">{exaggeration.toFixed(1)}×</span>
            </span>
            <input
              name="exageracion-relieve"
              type="range"
              min={1}
              max={3}
              step={0.1}
              value={exaggeration}
              onChange={(e) => setExaggeration(Number(e.target.value))}
              className="accent-accent pointer-coarse:h-11"
            />
            <span className="text-xs text-ink-muted">
              {t(
                'Inclinar y girar: clic derecho (o Ctrl) y arrastrar; en táctil, dos dedos en vertical. La brújula vuelve al norte.',
              )}
            </span>
          </label>
        )}
      </section>

      <Group title="Fuego">
        <Toggle
          id="detecciones"
          label="Incendios detectados"
          origin="real"
          legend={
            <div className="flex flex-col gap-1">
              <span className="text-xs text-ink-muted">
                NASA FIRMS,{' '}
                {detections
                  ? t('{a} a {b}', { a: detections.from, b: detections.to })
                  : load.status === 'error'
                    ? t('no se han podido descargar')
                    : t('cargando…')}
                . {t('Celdas de 250 m con fuego detectado.')}
              </span>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                <span className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="size-3 rounded-full border-2 border-[#fff1d6] bg-[#c2331f]"
                  />
                  {t('Activo al cierre del dato')}
                </span>
                <span className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="size-3 rounded-full border-2 border-[#d9905a] bg-[#1d2026]"
                  />
                  {t('Sin detecciones al cierre')}
                </span>
                <span className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="size-3 rotate-45 border-2 border-[#e0a640] bg-[#2a2110]"
                  />
                  {t('Simulación')}
                </span>
              </div>
            </div>
          }
        />
        <Toggle
          id="halo"
          label="Halo de avance de los reales"
          origin="ilustrativa"
          legend={
            <div className="flex flex-col gap-1">
              <Swatch fill={HALO_COLOR}>Hasta dónde podría llegar en 6 h</Swatch>
              <span className="text-xs text-ink-muted">
                {t(
                  'No es un pronóstico: FIRMS no da el viento y se usa un poniente fijo de ejemplo (15 km/h). Solo en los incendios con actividad al cierre del dato.',
                )}
              </span>
            </div>
          }
        />
        <Toggle
          id="incendio"
          label="Incendio activo"
          origin="simulado"
          legend={<Swatch fill={ACTIVE_COLOR}>Zona ardiendo ahora (celdas de 250 m)</Swatch>}
        />
        <Toggle
          id="prediccion"
          label="Propagación prevista"
          origin="modelo"
          legend={
            <div className="flex flex-col gap-1">
              <span className="text-xs text-ink-muted">
                {t('Modelo de demostración: dónde llegaría el fuego, no dónde está.')}
              </span>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {PREDICTION_BANDS.map(([h, c, label, pattern]) => (
                  <Swatch key={h} fill={c} hatch={pattern}>
                    {label}
                  </Swatch>
                ))}
              </div>
            </div>
          }
        />
      </Group>

      <Group title="Histórico">
        <Toggle
          id="mes"
          label="Actividad del mes del calendario"
          origin="real"
          legend={
            <div className="flex flex-col gap-1">
              <span className="flex items-center gap-2 text-xs">
                {t('Menos')}
                <span
                  aria-hidden
                  className="h-2.5 flex-1 rounded-[2px]"
                  style={{
                    background: `linear-gradient(90deg, ${MONTH_RAMP.map(([, c]) => c).join(', ')})`,
                  }}
                />
                {t('Más')}
              </span>
              <span className="text-xs text-ink-muted">
                {t(
                  'Celdas de 5 km del mes elegido en el calendario, en detecciones equivalentes MODIS. Pulsa otro mes para cambiarla.',
                )}
              </span>
              <Swatch fill={AREA_COLOR}>Área de interés del calendario</Swatch>
            </div>
          }
        />
      </Group>

      <Group title="Operativo">
        <Toggle id="unidades" label="Unidades" origin="simulado" />
        <Toggle
          id="evacuacion"
          label="Vías de escape"
          origin="simulado"
          legend={
            <div className="flex flex-col gap-1">
              <Swatch fill="var(--color-route)">Ruta hasta el refugio</Swatch>
              <span className="text-xs text-ink-muted">
                {t(
                  'Calculadas con el algoritmo de evacuación del equipo sobre carreteras de OpenStreetMap, teniendo en cuenta cómo avanzaría el fuego.',
                )}
              </span>
            </div>
          }
        />
      </Group>

      <Group title="Terreno">
        <Toggle
          id="curvas"
          label="Curvas de nivel"
          disabled={provider.contours ? undefined : 'Requiere la clave de MapTiler.'}
        />
        <Toggle id="sombreado" label="Sombreado del relieve" />
      </Group>

      <p className="m-0 border-t border-line px-4 py-2 text-xs text-ink-muted">
        {t('Cartografía:')} {provider.attribution}
      </p>
    </aside>
  );
}
