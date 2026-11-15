// Cliente del backend (FastAPI). En la web publicada se conecta solo (VITE_API_URL del build);
// si no responde, la app sigue con sus datos estáticos. Para desarrollo, `?api=` en la dirección
// elige otro servidor solo para esa pestaña.

/** Clave antigua: versiones anteriores guardaban aquí la URL elegida en Ajustes */
const LEGACY_KEY = 'cataclismo.api';
const SESSION_KEY = 'cataclismo.api';

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

/** sessionStorage puede faltar o lanzar (modo privado, datos bloqueados) */
function session(): Storage | undefined {
  try {
    return window.sessionStorage;
  } catch {
    return undefined;
  }
}

/**
 * URL inicial del backend ('' = sin backend). `?api=` vale para la pestaña (sobrevive a recargar);
 * `?api=` vacío desactiva el backend en ella. Si no, la del build.
 */
export function initialApiBase(): string {
  // Una URL guardada por una versión anterior no debe tapar la de producción
  try {
    window.localStorage.removeItem(LEGACY_KEY);
  } catch {
    // sin almacenamiento: nada que limpiar
  }
  const query = fromQuery();
  const store = session();
  if (query !== null) {
    const base = normalizeBase(query);
    const value = validBase(base) ? base : '';
    try {
      store?.setItem(SESSION_KEY, value);
    } catch {
      // sin almacenamiento: vale solo hasta recargar
    }
    return value;
  }
  let chosen: string | null = null;
  try {
    chosen = store?.getItem(SESSION_KEY) ?? null;
  } catch {
    chosen = null;
  }
  if (chosen !== null) return validBase(chosen) ? chosen : '';
  return defaultApiBase(window.location.hostname, import.meta.env.VITE_API_URL);
}

/**
 * URL del build (VITE_API_URL), solo fuera de localhost: en local (desarrollo, e2e y Lighthouse
 * del CI) la app no depende de un servidor externo salvo que se pida con ?api=.
 */
export function defaultApiBase(hostname: string, env: string | undefined): string {
  if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]') return '';
  const base = normalizeBase(env ?? '');
  return validBase(base) ? base : '';
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
