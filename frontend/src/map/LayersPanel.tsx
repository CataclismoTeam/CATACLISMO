import { Eye, EyeOff, Layers, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn.ts';
import { useUi, type Basemap, type LayerId } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import type { Detections } from './detections.ts';
import type { Remote } from './useRemote.ts';
import { ACTIVE_COLOR, PREDICTION_BANDS } from './overlays.ts';
import { provider } from './providers.ts';

const BASEMAPS: [Basemap, string][] = [
  ['satelite', 'Satélite'],
  ['topografico', 'Topográfico'],
];

type Origin = 'real' | 'simulado' | 'modelo';
const ORIGIN: Record<Origin, { label: string; className: string }> = {
  real: { label: 'Real', className: 'border-ok/60 text-ok' },
  simulado: { label: 'Simulado', className: 'border-warn/60 text-warn' },
  modelo: { label: 'Predicción', className: 'border-water/60 text-water' },
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
  return (
    <li className="border-t border-line py-2 first:border-t-0">
      <button
        type="button"
        aria-pressed={on}
        disabled={!!disabled}
        title={disabled}
        onClick={() => toggle(id)}
        className="flex min-h-9 w-full cursor-pointer items-center gap-2 rounded-sm text-left text-sm disabled:cursor-not-allowed disabled:opacity-50 pointer-coarse:min-h-11"
      >
        {on ? (
          <Eye size={16} strokeWidth={1.5} aria-hidden className="shrink-0 text-accent" />
        ) : (
          <EyeOff size={16} strokeWidth={1.5} aria-hidden className="shrink-0 text-ink-muted" />
        )}
        <span className={cn('flex-1', !on && 'text-ink-muted')}>{label}</span>
        {origin && (
          <span
            className={cn(
              'rounded-sm border px-1.5 text-xs font-semibold uppercase',
              ORIGIN[origin].className,
            )}
          >
            {ORIGIN[origin].label}
          </span>
        )}
      </button>
      {disabled && <p className="m-0 mt-1 pl-6 text-xs text-ink-muted">{disabled}</p>}
      {on && legend && <div className="mt-1.5 pl-6">{legend}</div>}
    </li>
  );
}

function Swatch({ fill, hatch, children }: { fill: string; hatch?: boolean; children: ReactNode }) {
  return (
    <span className="flex items-center gap-2 text-xs">
      <span
        aria-hidden
        className="size-3.5 shrink-0 rounded-[2px] border border-line-strong"
        style={{
          background: hatch
            ? `repeating-linear-gradient(135deg, ${fill} 0 3px, transparent 3px 6px)`
            : fill,
        }}
      />
      {children}
    </span>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line px-4 py-3">
      <h3 className="m-0 mb-1 text-xs font-semibold tracking-wide text-ink-muted uppercase">
        {title}
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

  if (!open) {
    return (
      <Button className="absolute top-3 right-14" onClick={() => setOpen(true)}>
        <Layers size={16} strokeWidth={1.5} aria-hidden />
        Capas
      </Button>
    );
  }

  return (
    <aside
      aria-label="Capas del mapa"
      className="absolute inset-x-0 bottom-0 z-(--z-panel) max-h-[70%] overflow-y-auto rounded-t-lg border border-line-strong bg-surface shadow-panel md:inset-x-auto md:top-3 md:right-14 md:bottom-auto md:max-h-[calc(100%-1.5rem)] md:w-80 md:rounded-lg"
    >
      <header className="sticky top-0 flex items-center justify-between bg-surface px-4 py-2">
        <h2 className="m-0 text-base font-semibold">Capas</h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Cerrar capas"
          onClick={() => setOpen(false)}
        >
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>

      <section className="px-4 pb-3">
        <h3 className="m-0 mb-1.5 text-xs font-semibold tracking-wide text-ink-muted uppercase">
          Mapa base
        </h3>
        <div role="radiogroup" aria-label="Mapa base" className="grid grid-cols-2 gap-1">
          {BASEMAPS.map(([id, label]) => (
            <Button
              key={id}
              role="radio"
              aria-checked={basemap === id}
              aria-pressed={basemap === id}
              className="px-2"
              onClick={() => setBasemap(id)}
            >
              {label}
            </Button>
          ))}
        </div>
        {mode === '3d' && (
          <label className="mt-3 flex flex-col gap-1 text-sm">
            <span className="flex justify-between">
              Exageración del relieve
              <span className="font-mono">{exaggeration.toFixed(1)}×</span>
            </span>
            <input
              type="range"
              min={1}
              max={3}
              step={0.1}
              value={exaggeration}
              onChange={(e) => setExaggeration(Number(e.target.value))}
              className="accent-accent pointer-coarse:h-11"
            />
            <span className="text-xs text-ink-muted">
              Inclina el mapa (clic derecho o dos dedos) para la vista 2.5D.
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
                  ? `${detections.from} a ${detections.to}`
                  : load.status === 'error'
                    ? 'no se han podido descargar'
                    : 'cargando…'}
                . Celdas de 250 m con fuego detectado y, alrededor, la propagación prevista.
              </span>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                <span className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="size-3 rounded-full border-2 border-[#fff1d6] bg-[#c2331f]"
                  />
                  Actividad reciente
                </span>
                <span className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="size-3 rounded-full border-2 border-[#d9905a] bg-[#1d2026]"
                  />
                  Sin actividad reciente
                </span>
                <span className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="size-3 rotate-45 border-2 border-[#e0a640] bg-[#2a2110]"
                  />
                  Simulación
                </span>
              </div>
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
                Modelo de demostración: dónde llegaría el fuego, no dónde está.
              </span>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {PREDICTION_BANDS.map(([h, c, label]) => (
                  <Swatch key={h} fill={c} hatch>
                    {label}
                  </Swatch>
                ))}
              </div>
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
                Calculadas con el algoritmo de evacuación del equipo sobre carreteras de
                OpenStreetMap, teniendo en cuenta cómo avanzaría el fuego.
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
        Cartografía: {provider.attribution}
      </p>
    </aside>
  );
}
