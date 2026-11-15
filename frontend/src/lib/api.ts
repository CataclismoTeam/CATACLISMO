// Cliente del backend (FastAPI). Es opcional: sin URL configurada la app sigue con sus datos
// estáticos. La URL sale, por orden, de `?api=` en la dirección, de lo guardado en Ajustes o de
// VITE_API_URL en el build.
import { readStored, writeStored } from './storage.ts';

const KEY = 'cataclismo.api';

/** Quita espacios y barras finales: `http://host:8000/` → `http://host:8000`. */
export const normalizeBase = (url: string): string => url.trim().replace(/\/+$/, '');

/** Solo http(s): cualquier otra cosa se ignora. */
export function validBase(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === 'http:' || protocol === 'https:';
  } catch {
    return false;
  }
}

function fromQuery(): string | null {
  try {
    return new URL(window.location.href).searchParams.get('api');
  } catch {
    return null;
  }
}

/** URL inicial del backend ('' = sin backend). `?api=` se recuerda; `?api=` vacío la olvida. */
export function initialApiBase(): string {
  const query = fromQuery();
  if (query !== null) {
    const base = normalizeBase(query);
    writeStored(KEY, validBase(base) ? base : '');
    return validBase(base) ? base : '';
  }
  const stored = normalizeBase(readStored<string>(KEY, ''));
  if (validBase(stored)) return stored;
  const env = normalizeBase(import.meta.env.VITE_API_URL ?? '');
  return validBase(env) ? env : '';
}

export function saveApiBase(base: string): void {
  writeStored(KEY, base);
}

export class ApiError extends Error {
  readonly status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

/** GET JSON con tiempo máximo: una API colgada no deja la interfaz esperando. */
export async function apiGet<T>(base: string, path: string, timeoutMs = 8000): Promise<T> {
  let response: Response;
  try {
    response = await fetch(base + path, {
      signal: AbortSignal.timeout(timeoutMs),
      headers: { Accept: 'application/json' },
    });
  } catch {
    throw new ApiError('sin conexión');
  }
  if (!response.ok) throw new ApiError(`HTTP ${response.status}`, response.status);
  return (await response.json()) as T;
}

/** WebSocket de eventos en vivo del backend (`/ws`), con el mismo host que la API. */
export const wsUrl = (base: string): string => `${base.replace(/^http/, 'ws')}/ws`;
