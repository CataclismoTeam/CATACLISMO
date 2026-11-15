import { locale, useT } from '../lib/i18n.ts';
import { Crosshair, X } from 'lucide-react';
import type { Map as MapLibre } from 'maplibre-gl';
import { useEffect, useState, type RefObject } from 'react';
import { cn } from '../lib/cn.ts';
import { Button } from '../ui/Button.tsx';
import { ago, shortDate, SOURCES } from '../lib/sources.ts';
import { Tag } from '../ui/Tag.tsx';
import { SourceLink } from '../ui/SourceLink.tsx';
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
      className={`${panel} m-0 flex max-w-full shrink-0 max-md:hidden items-center gap-3 px-3 py-1.5 font-mono text-sm`}
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
  const t = useT();
  const status = STATUS[unit.status];
  return (
    <section
      aria-label={t('Ficha de {x}', { x: t(unit.name) })}
      className={`${panel} min-h-0 w-88 max-w-full overflow-y-auto p-4`}
    >
      <header className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="m-0 text-xs font-semibold tracking-wide text-ink-muted uppercase">
            {t(KIND[unit.kind].label)} · {unit.id}
          </p>
          <h3 className="m-0 text-base font-semibold">{t(unit.name)}</h3>
        </div>
        <Button variant="ghost" size="icon" aria-label={t('Cerrar ficha')} onClick={onClose}>
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-ink-muted">{t('Estado')}</dt>
        <dd className="m-0 font-semibold" style={{ color: status.color }}>
          {t(status.label)}
        </dd>
        <dt className="text-ink-muted">{t('Medio')}</dt>
        <dd className="m-0">
          {t(DOMAIN_LABEL[unit.domain])}
          {unit.group ? ` · ${t(unit.group)}` : ''}
        </dd>
        <dt className="text-ink-muted">{t('Dotación')}</dt>
        <dd className="m-0">{t('{n} personas', { n: unit.crew })}</dd>
        <dt className="text-ink-muted">{t('Posición')}</dt>
        <dd className="m-0 font-mono">
          {lat(unit.lat)} {lon(unit.lon)}
        </dd>
        <dt className="text-ink-muted">{t('Hora de simulación')}</dt>
        <dd className="m-0 font-mono">{unit.updated.slice(11, 16)} UTC</dd>
      </dl>
      <Tag tone="simulado" className="mt-3">
        {t('Unidad simulada')}
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
  const t = useT();
  return (
    <section
      aria-label={t('Detalle del fuego')}
      className={`${panel} min-h-0 w-88 max-w-full overflow-y-auto p-4`}
    >
      <header className="mb-2 flex items-start justify-between gap-2">
        <div>
          <p className="m-0 text-xs font-semibold tracking-wide text-fire uppercase">
            {t('Foco térmico · simulado')}
          </p>
          <h3 className="m-0 text-base font-semibold">{t('Detalle de intensidad')}</h3>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t('Cerrar detalle del fuego')}
          onClick={onClose}
        >
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-ink-muted">{t('Intensidad')}</dt>
        <dd className="m-0 font-semibold text-fire">
          {Math.round(observation.intensity).toLocaleString(locale())} MW
        </dd>
        <dt className="text-ink-muted">{t('Altura de llama')}</dt>
        <dd className="m-0">{observation.flameHeight} m</dd>
        <dt className="text-ink-muted">{t('Llegada estimada')}</dt>
        <dd className="m-0">{observation.arrivalHours.toFixed(1)} h</dd>
        <dt className="text-ink-muted">{t('Coordenadas')}</dt>
        <dd className="m-0 font-mono">
          {observation.lat.toFixed(5)} / {observation.lon.toFixed(5)}
        </dd>
      </dl>
      <Tag tone="simulado" className="mt-3">
        {t('Modelo de demostración')}
      </Tag>
    </section>
  );
}

/** Ficha de un incendio detectado por satélite (REAL). */
export function IncidentCard({
  incident,
  dataEnd,
  onClose,
}: {
  incident: Incident;
  /** Último día de los datos de incendios (AAAA-MM-DD) */
  dataEnd?: string;
  onClose: () => void;
}) {
  const t = useT();
  const [lon0, lat0, lon1, lat1] = incident.bbox;
  // Visor de FIRMS centrado en el incendio y con sus fechas
  const firmsMap = `https://firms.modaps.eosdis.nasa.gov/map/#d:${incident.desde}..${incident.hasta};@${((lon0 + lon1) / 2).toFixed(3)},${((lat0 + lat1) / 2).toFixed(3)},11.0z`;
  // Ficha en el lateral, bajo el panel de capas (ver la pila de esquina en MapView)
  const area =
    incident.areaKm2 < 1
      ? `${Math.round(incident.areaKm2 * 100)} ha`
      : `${incident.areaKm2.toLocaleString(locale(), { maximumFractionDigits: 1 })} km²`;
  return (
    <section
      aria-label={`${t('Incendio')} ${incident.id}`}
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
          aria-label={t('Cerrar ficha del incendio')}
          onClick={onClose}
        >
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-ink-muted">{t('Estado')}</dt>
        <dd className="m-0 font-semibold">
          {incident.activo
            ? `${t('Activo al cierre del dato')}${dataEnd ? ` (${shortDate(dataEnd)})` : ''}`
            : t('Sin detecciones al cierre del dato')}
        </dd>
        <dt className="text-ink-muted">{t('Última detección')}</dt>
        <dd className="m-0">
          <span className="font-mono">{incident.hasta}</span>{' '}
          <span data-dinamico className="text-ink-muted">
            ({ago(incident.hasta)})
          </span>
        </dd>
        <dt className="text-ink-muted">{t('Detectado')}</dt>
        <dd className="m-0 font-mono">
          {incident.desde === incident.hasta
            ? incident.desde
            : `${incident.desde} → ${incident.hasta}`}
        </dd>
        <dt className="text-ink-muted">{t('Detecciones')}</dt>
        <dd className="m-0">
          {incident.detecciones.toLocaleString(locale())} ({incident.sensores.join(` ${t('y')} `)})
        </dd>
        <dt className="text-ink-muted">{t('Área afectada')}</dt>
        <dd className="m-0">≈ {area}</dd>
        <dt className="text-ink-muted">{t('Potencia máx.')}</dt>
        <dd className="m-0">{incident.frpMax.toLocaleString(locale())} MW</dd>
      </dl>
      <p className="m-0 mt-2 text-xs text-ink-muted">
        {t('Área estimada con la huella de los píxeles del satélite; no es un perímetro oficial.')}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        <Tag tone="real">{t('Real · NASA FIRMS')}</Tag>
        <SourceLink
          source={{ ...SOURCES.firms, name: t('Ver en el visor de FIRMS'), url: firmsMap }}
          className="text-sm"
        />
      </div>
    </section>
  );
}
