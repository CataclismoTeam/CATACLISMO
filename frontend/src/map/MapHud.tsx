import { ArrowUp, Crosshair, X } from 'lucide-react';
import type { Map as MapLibre } from 'maplibre-gl';
import { useEffect, useState, type RefObject } from 'react';
import { useUi, type ScenarioId } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { Tag } from '../ui/Tag.tsx';
import { KIND, STATUS } from './markers.ts';
import { SCENARIOS, type Scenario, type Unit } from './scenario.ts';

const panel = 'rounded-md border border-line-strong bg-surface shadow-panel';
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'];

/** Escenario activo, viento y rótulo de simulación (arriba a la izquierda). */
export function ScenarioBar({ scenario }: { scenario: Scenario }) {
  const setScenario = useUi((s) => s.setScenario);
  const from = COMPASS[Math.round(scenario.windFrom / 45) % 8];
  return (
    <div
      className={`${panel} absolute top-3 left-3 flex max-w-[calc(100%-5rem)] flex-col gap-2 p-3`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone="simulado">Escenario simulado</Tag>
        <label className="sr-only" htmlFor="escenario">
          Escenario
        </label>
        <select
          id="escenario"
          value={scenario.id}
          onChange={(e) => setScenario(e.target.value as ScenarioId)}
          className="h-9 min-w-0 rounded-md border border-line-strong bg-canvas px-2 text-sm font-semibold text-ink pointer-coarse:h-11"
        >
          {Object.values(SCENARIOS).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      <p className="m-0 hidden max-w-sm text-sm text-ink-muted sm:block">{scenario.description}</p>
      <p className="m-0 hidden items-center gap-2 text-sm sm:flex">
        <span
          className="grid size-7 place-items-center rounded-full border border-line-strong"
          title={`El viento sopla hacia ${COMPASS[Math.round(((scenario.windFrom + 180) % 360) / 45) % 8]}`}
        >
          <ArrowUp
            size={16}
            strokeWidth={2}
            aria-hidden
            style={{ transform: `rotate(${(scenario.windFrom + 180) % 360}deg)` }}
          />
        </span>
        Viento del {from}, {scenario.windKmh} km/h
      </p>
    </div>
  );
}

// Decimales con signo (WGS84): sin letras O/W que se confundan con un cero
const lat = (v: number) => `${v.toFixed(5)}`;
const lon = (v: number) => `${v.toFixed(5)}`;

/** Coordenadas y altitud bajo el cursor (o del centro en pantallas táctiles). */
export function CoordinatesBar({
  map,
  ready,
}: {
  map: RefObject<MapLibre | null>;
  ready: boolean;
}) {
  const [pos, setPos] = useState<{ lat: number; lon: number; alt: number | null }>();

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    let frame = 0;
    const update = (lngLat: { lng: number; lat: number }) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const alt = m.getTerrain() ? m.queryTerrainElevation(lngLat) : null;
        setPos({ lat: lngLat.lat, lon: lngLat.lng, alt });
      });
    };
    const onMove = (e: { lngLat: { lng: number; lat: number } }) => update(e.lngLat);
    const onCenter = () => update(m.getCenter());
    m.on('mousemove', onMove);
    m.on('moveend', onCenter);
    onCenter();
    return () => {
      cancelAnimationFrame(frame);
      m.off('mousemove', onMove);
      m.off('moveend', onCenter);
    };
  }, [map, ready]);

  if (!pos) return null;
  return (
    <p
      aria-live="off"
      className={`${panel} absolute bottom-10 left-3 m-0 flex items-center gap-3 px-3 py-1.5 font-mono text-sm`}
    >
      <Crosshair size={16} strokeWidth={1.5} aria-hidden className="text-ink-muted" />
      <span>
        <span className="text-ink-muted">Lat </span>
        {lat(pos.lat)}
      </span>
      <span>
        <span className="text-ink-muted">Lon </span>
        {lon(pos.lon)}
      </span>
      {pos.alt !== null && Number.isFinite(pos.alt) && (
        <span className="text-ink-muted">{Math.round(pos.alt)} m</span>
      )}
    </p>
  );
}

/** Ficha de la unidad seleccionada. */
export function UnitCard({ unit, onClose }: { unit: Unit; onClose: () => void }) {
  const status = STATUS[unit.status];
  return (
    <section
      aria-label={`Ficha de ${unit.name}`}
      className={`${panel} absolute bottom-24 left-3 w-[min(22rem,calc(100%-1.5rem))] p-4`}
    >
      <header className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="m-0 text-xs font-semibold tracking-wide text-ink-muted uppercase">
            {KIND[unit.kind].label} · {unit.id}
          </p>
          <h3 className="m-0 text-base font-semibold">{unit.name}</h3>
        </div>
        <Button variant="ghost" size="icon" aria-label="Cerrar ficha" onClick={onClose}>
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-ink-muted">Estado</dt>
        <dd className="m-0 font-semibold" style={{ color: status.color }}>
          {status.label}
        </dd>
        <dt className="text-ink-muted">Dotación</dt>
        <dd className="m-0">{unit.crew} personas</dd>
        <dt className="text-ink-muted">Posición</dt>
        <dd className="m-0 font-mono">
          {lat(unit.lat)} {lon(unit.lon)}
        </dd>
        <dt className="text-ink-muted">Actualizado</dt>
        <dd className="m-0 font-mono">{unit.updated.slice(11, 16)} UTC</dd>
      </dl>
      <Tag tone="simulado" className="mt-3">
        Unidad simulada
      </Tag>
    </section>
  );
}
