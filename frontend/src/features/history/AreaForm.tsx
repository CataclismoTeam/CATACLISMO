import { Crosshair, SquareDashed } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { formatArea, formatCount } from '../../lib/format.ts';
import { useHistory } from '../../store/history.ts';
import { useUi } from '../../store/ui.ts';
import type { Area } from './area.ts';
import { areaRing, ringBbox } from './mapLayers.ts';
import { Button } from '../../ui/Button.tsx';
import { Field, Input, Select } from '../../ui/Field.tsx';
import { AREA_PRESETS } from './presets.ts';
import { METRIC_LABEL, type Metric } from './series.ts';

const CUSTOM = 'personalizada';
const DRAWN = 'Área dibujada';

/** Encuadra el área en el mapa (nada para «toda España»). */
function frame(area: Area) {
  const ring = areaRing(area);
  if (ring) useUi.getState().flyTo(ringBbox(ring));
}

function parse(text: string): number {
  return Number(text.trim().replace(',', '.'));
}

/** Área de interés, rango de años y serie que se muestra. */
export function AreaForm() {
  const area = useHistory((s) => s.area);
  const cells = useHistory((s) => s.cells);
  const manifest = useHistory((s) => s.manifest);
  const yearRange = useHistory((s) => s.yearRange);
  const metric = useHistory((s) => s.metric);
  const storeSetArea = useHistory((s) => s.setArea);
  // Cambiar el área desde el formulario también la encuadra en el mapa
  const setArea = (next: Area) => {
    storeSetArea(next);
    frame(next);
  };
  const drawing = useUi((s) => s.mapTool === 'dibujar');
  const setMapTool = useUi((s) => s.setMapTool);
  const setYearRange = useHistory((s) => s.setYearRange);
  const setMetric = useHistory((s) => s.setMetric);

  const preset = AREA_PRESETS.find((p) => p.name === area.name);
  const drawn = area.kind === 'bbox' && area.name === DRAWN;
  const [custom, setCustom] = useState(!preset && !drawn);
  const [lat, setLat] = useState('36.49');
  const [lon, setLon] = useState('-5.20');
  const [radius, setRadius] = useState('25');
  const [error, setError] = useState('');

  if (!manifest) return null;
  const grid = manifest.rejilla;
  const first = manifest.tiempo.anioInicial;
  const years = Array.from({ length: manifest.tiempo.meses / 12 }, (_, i) => first + i);

  const apply = (event: FormEvent) => {
    event.preventDefault();
    const [la, lo, r] = [parse(lat), parse(lon), parse(radius)];
    if (!(la >= grid.sur && la <= grid.norte && lo >= grid.oeste && lo <= grid.este)) {
      setError(
        `El punto queda fuera de los datos. Latitud entre ${grid.sur} y ${grid.norte}; longitud entre ${grid.oeste} y ${grid.este}.`,
      );
      return;
    }
    if (!(r >= 3 && r <= 500)) {
      setError('El radio debe estar entre 3 y 500 km.');
      return;
    }
    setError('');
    setArea({ kind: 'circle', name: 'Área personalizada', lat: la, lon: lo, radiusKm: r });
  };

  return (
    <div className="flex flex-col gap-3">
      <Field label="Área de interés">
        <Select
          name="area"
          value={custom ? CUSTOM : area.name}
          onChange={(e) => {
            if (e.target.value === DRAWN) return;
            const next = AREA_PRESETS.find((p) => p.name === e.target.value);
            setCustom(!next);
            setError('');
            if (next) setArea(next);
          }}
        >
          {AREA_PRESETS.map((p) => (
            <option key={p.name}>{p.name}</option>
          ))}
          {drawn && <option value={DRAWN}>{DRAWN}</option>}
          <option value={CUSTOM}>Punto y radio…</option>
        </Select>
      </Field>

      <div className="flex flex-wrap gap-2">
        <Button
          aria-pressed={drawing}
          onClick={() => {
            setCustom(false);
            setMapTool(drawing ? null : 'dibujar');
          }}
        >
          <SquareDashed size={16} strokeWidth={1.5} aria-hidden />
          {drawing ? 'Dibujando… (Esc)' : 'Dibujar en el mapa'}
        </Button>
        {area.kind !== 'all' && (
          <Button variant="ghost" onClick={() => frame(area)}>
            <Crosshair size={16} strokeWidth={1.5} aria-hidden />
            Ver en el mapa
          </Button>
        )}
      </div>

      {custom && (
        <form onSubmit={apply} className="flex flex-col gap-2" noValidate>
          <div className="grid grid-cols-3 gap-2">
            <Field label="Latitud">
              <Input
                name="latitud"
                inputMode="decimal"
                value={lat}
                aria-invalid={!!error}
                onChange={(e) => setLat(e.target.value)}
              />
            </Field>
            <Field label="Longitud">
              <Input
                name="longitud"
                inputMode="decimal"
                value={lon}
                aria-invalid={!!error}
                onChange={(e) => setLon(e.target.value)}
              />
            </Field>
            <Field label="Radio" hint="km">
              <Input
                name="radio"
                inputMode="decimal"
                value={radius}
                aria-invalid={!!error}
                onChange={(e) => setRadius(e.target.value)}
              />
            </Field>
          </div>
          {error && (
            <p role="alert" className="m-0 text-sm text-fire">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary">
            Aplicar área
          </Button>
        </form>
      )}

      <p className="m-0 text-sm text-ink-muted" aria-live="polite">
        {!cells
          ? 'Calculando la superficie del área…'
          : area.kind === 'all'
            ? `Toda el área con datos: ${formatCount(cells.dataCells)} celdas de 5 km con detecciones`
            : `${formatArea(cells.km2)} · ${formatCount(cells.gridCells)} celdas de 5 km, ${formatCount(cells.dataCells)} con detecciones`}
      </p>

      <div className="grid grid-cols-2 gap-2">
        <Field label="Desde">
          <Select
            name="desde"
            value={yearRange[0]}
            onChange={(e) => setYearRange([Number(e.target.value), yearRange[1]])}
          >
            {years
              .filter((y) => y <= yearRange[1])
              .map((y) => (
                <option key={y}>{y}</option>
              ))}
          </Select>
        </Field>
        <Field label="Hasta">
          <Select
            name="hasta"
            value={yearRange[1]}
            onChange={(e) => setYearRange([yearRange[0], Number(e.target.value)])}
          >
            {years
              .filter((y) => y >= yearRange[0])
              .map((y) => (
                <option key={y}>{y}</option>
              ))}
          </Select>
        </Field>
      </div>

      <Field label="Serie">
        <Select name="serie" value={metric} onChange={(e) => setMetric(e.target.value as Metric)}>
          {(Object.keys(METRIC_LABEL) as Metric[]).map((m) => (
            <option key={m} value={m}>
              {METRIC_LABEL[m]}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  );
}
