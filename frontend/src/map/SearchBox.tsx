import { MapPin, Search, X } from 'lucide-react';
import { useId, useRef, useState, type FormEvent } from 'react';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { parseCoords } from './coords.ts';
import { MAPTILER_KEY } from './providers.ts';

interface Place {
  name: string;
  bbox: [number, number, number, number];
}

const around = ([lon, lat]: [number, number], d = 0.01): [number, number, number, number] => [
  lon - d,
  lat - d,
  lon + d,
  lat + d,
];

interface GeocodingFeature {
  place_name?: string;
  text?: string;
  bbox?: [number, number, number, number];
  center?: [number, number];
}

async function geocode(query: string): Promise<Place[]> {
  const url = `https://api.maptiler.com/geocoding/${encodeURIComponent(query)}.json?key=${MAPTILER_KEY}&country=es&language=es&limit=5`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(String(response.status));
  const data = (await response.json()) as { features?: GeocodingFeature[] };
  return (data.features ?? [])
    .filter((f) => f.bbox || f.center)
    .map((f) => ({
      name: f.place_name ?? f.text ?? 'Lugar',
      bbox: f.bbox ?? around(f.center!),
    }));
}

/**
 * Buscador del mapa: coordenadas «lat, lon» vuelan directas; el texto va a la geocodificación de
 * MapTiler (necesita su clave). Dice claramente si falta la clave o no hay red.
 */
export function SearchBox({ className, autoFocus }: { className?: string; autoFocus?: boolean }) {
  const flyTo = useUi((s) => s.flyTo);
  const [query, setQuery] = useState('');
  const [places, setPlaces] = useState<Place[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();

  const go = (bbox: [number, number, number, number]) => {
    flyTo(bbox);
    setPlaces([]);
    setMessage('');
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const q = query.trim();
    if (!q) return;
    const coords = parseCoords(q);
    if (coords) {
      go(around(coords));
      return;
    }
    if (!MAPTILER_KEY) {
      setPlaces([]);
      setMessage(
        'Buscar lugares por nombre necesita la clave de MapTiler. Prueba con coordenadas: 36.49, -5.2',
      );
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      const found = await geocode(q);
      setPlaces(found);
      if (!found.length) setMessage(`No se ha encontrado «${q}» en España.`);
    } catch {
      setPlaces([]);
      setMessage(
        navigator.onLine
          ? 'El buscador no responde ahora. Prueba con coordenadas: 36.49, -5.2'
          : 'Sin conexión: solo se puede buscar por coordenadas (36.49, -5.2).',
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn('relative', className)}>
      <form role="search" aria-label="Buscar en el mapa" onSubmit={submit} className="flex">
        <label className="relative flex min-w-0 flex-1 items-center">
          <span className="sr-only">Buscar un lugar o coordenadas</span>
          <Search
            size={16}
            strokeWidth={1.5}
            aria-hidden
            className="pointer-events-none absolute left-2.5 text-ink-muted"
          />
          <input
            name="busqueda"
            ref={input}
            type="search"
            value={query}
            autoFocus={autoFocus}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setPlaces([]);
                setMessage('');
              }
            }}
            placeholder="Lugar o «lat, lon»"
            aria-controls={places.length ? listId : undefined}
            aria-busy={busy}
            className="h-9 w-full min-w-0 rounded-md border border-line-strong bg-canvas pr-2 pl-8 text-sm text-ink placeholder:text-ink-muted pointer-coarse:h-11"
          />
        </label>
      </form>
      {(places.length > 0 || message) && (
        <div className="absolute top-full right-0 left-0 z-(--z-overlay) mt-1 rounded-md border border-line-strong bg-surface p-1 shadow-panel">
          {message && (
            <p role="status" className="m-0 flex items-start gap-2 px-2 py-1.5 text-sm">
              {message}
              <Button
                variant="ghost"
                size="icon"
                aria-label="Cerrar aviso de búsqueda"
                className="-my-1 ml-auto"
                onClick={() => setMessage('')}
              >
                <X size={16} strokeWidth={1.5} aria-hidden />
              </Button>
            </p>
          )}
          {places.length > 0 && (
            <ul id={listId} aria-label="Resultados" className="m-0 list-none p-0">
              {places.map((p) => (
                <li key={p.name + p.bbox.join()}>
                  <button
                    type="button"
                    onClick={() => go(p.bbox)}
                    className="flex w-full cursor-pointer items-start gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-hover pointer-coarse:min-h-11"
                  >
                    <MapPin size={16} strokeWidth={1.5} aria-hidden className="mt-0.5 shrink-0" />
                    {p.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
