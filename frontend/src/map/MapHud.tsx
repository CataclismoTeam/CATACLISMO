import { Crosshair, X } from 'lucide-react';
import type { Map as MapLibre } from 'maplibre-gl';
import { useEffect, useState, type RefObject } from 'react';
import { cn } from '../lib/cn.ts';
import { Button } from '../ui/Button.tsx';
import { Tag } from '../ui/Tag.tsx';
import { KIND, STATUS } from './markers.ts';
import type { Incident } from './incidents.ts';
import { DOMAIN_LABEL, type Unit } from './scenario.ts';

const panel = 'rounded-md border border-line-strong bg-surface shadow-panel';

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
      className={`${panel} m-0 flex max-w-full shrink-0 items-center gap-3 px-3 py-1.5 font-mono text-sm`}
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
      className={`${panel} min-h-0 w-88 max-w-full overflow-y-auto p-4`}
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
        <dt className="text-ink-muted">Medio</dt>
        <dd className="m-0">
          {DOMAIN_LABEL[unit.domain]}
          {unit.group ? ` · ${unit.group}` : ''}
        </dd>
        <dt className="text-ink-muted">Dotación</dt>
        <dd className="m-0">{unit.crew} personas</dd>
        <dt className="text-ink-muted">Posición</dt>
        <dd className="m-0 font-mono">
          {lat(unit.lat)} {lon(unit.lon)}
        </dd>
        <dt className="text-ink-muted">Hora de simulación</dt>
        <dd className="m-0 font-mono">{unit.updated.slice(11, 16)} UTC</dd>
      </dl>
      <Tag tone="simulado" className="mt-3">
        Unidad simulada
      </Tag>
    </section>
  );
}

export interface FireObservation {
  lon: number;
  lat: number;
  intensity: number;
  flameHeight: number;
  arrivalHours: number;
}

export function FireCard({
  observation,
  onClose,
}: {
  observation: FireObservation;
  onClose: () => void;
}) {
  return (
    <section
      aria-label="Detalle del fuego"
      className={`${panel} min-h-0 w-88 max-w-full overflow-y-auto p-4`}
    >
      <header className="mb-2 flex items-start justify-between gap-2">
        <div>
          <p className="m-0 text-xs font-semibold tracking-wide text-fire uppercase">
            Foco térmico · simulado
          </p>
          <h3 className="m-0 text-base font-semibold">Detalle de intensidad</h3>
        </div>
        <Button variant="ghost" size="icon" aria-label="Cerrar detalle del fuego" onClick={onClose}>
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-ink-muted">Intensidad</dt>
        <dd className="m-0 font-semibold text-fire">
          {Math.round(observation.intensity).toLocaleString('es-ES')} MW
        </dd>
        <dt className="text-ink-muted">Altura de llama</dt>
        <dd className="m-0">{observation.flameHeight} m</dd>
        <dt className="text-ink-muted">Llegada estimada</dt>
        <dd className="m-0">{observation.arrivalHours.toFixed(1)} h</dd>
        <dt className="text-ink-muted">Coordenadas</dt>
        <dd className="m-0 font-mono">
          {observation.lat.toFixed(5)} / {observation.lon.toFixed(5)}
        </dd>
      </dl>
      <Tag tone="simulado" className="mt-3">
        Modelo de demostración
      </Tag>
    </section>
  );
}

/** Ficha de un incendio detectado por satélite (REAL). */
export function IncidentCard({ incident, onClose }: { incident: Incident; onClose: () => void }) {
  // Ficha en el lateral, bajo el panel de capas (ver la pila de esquina en MapView)
  const area =
    incident.areaKm2 < 1
      ? `${Math.round(incident.areaKm2 * 100)} ha`
      : `${incident.areaKm2.toLocaleString('es-ES', { maximumFractionDigits: 1 })} km²`;
  return (
    <section
      aria-label={`Incendio ${incident.id}`}
      className={cn(
        panel,
        'overflow-y-auto p-4 max-md:absolute max-md:inset-x-3 max-md:top-14 max-md:max-h-[calc(100%-4.25rem)] md:min-h-0 md:w-88',
      )}
    >
      <header className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="m-0 text-xs font-semibold tracking-wide text-ink-muted uppercase">
            {incident.comunidad} · {incident.id}
          </p>
          <h3 className="m-0 text-base font-semibold">{incident.provincia}</h3>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Cerrar ficha del incendio"
          onClick={onClose}
        >
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-ink-muted">Estado</dt>
        <dd className="m-0 font-semibold">
          {incident.activo ? 'Con actividad reciente' : 'Sin detecciones recientes'}
        </dd>
        <dt className="text-ink-muted">Detectado</dt>
        <dd className="m-0 font-mono">
          {incident.desde === incident.hasta
            ? incident.desde
            : `${incident.desde} → ${incident.hasta}`}
        </dd>
        <dt className="text-ink-muted">Detecciones</dt>
        <dd className="m-0">
          {incident.detecciones.toLocaleString('es-ES')} ({incident.sensores.join(' y ')})
        </dd>
        <dt className="text-ink-muted">Área afectada</dt>
        <dd className="m-0">≈ {area}</dd>
        <dt className="text-ink-muted">Potencia máx.</dt>
        <dd className="m-0">{incident.frpMax.toLocaleString('es-ES')} MW</dd>
      </dl>
      <p className="m-0 mt-2 text-xs text-ink-muted">
        Área estimada con la huella de los píxeles del satélite; no es un perímetro oficial.
      </p>
      <Tag tone="real" className="mt-3">
        Real · NASA FIRMS
      </Tag>
    </section>
  );
}
