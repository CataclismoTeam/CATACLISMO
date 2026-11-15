import { useEffect } from 'react';
import { create } from 'zustand';
import { apiGet, initialApiBase, normalizeBase, saveApiBase, validBase } from '../lib/api.ts';
import type { JuliCollection, LuciaCollection } from '../map/backend.ts';

/** apagado: sin URL · conectando: primera comprobación · conectado · sin-conexion: no responde */
export type BackendStatus = 'apagado' | 'conectando' | 'conectado' | 'sin-conexion';

export interface LiveStatus {
  status: string;
  firms_key_configured?: boolean;
}

interface BackendState {
  base: string;
  status: BackendStatus;
  /** Base de datos PostGIS del backend ('ok' | 'unavailable') */
  database?: string;
  live?: LiveStatus;
  /** WebSocket /ws abierto: JULI llega en vivo */
  socket: boolean;
  /** Salida de CATA + LUCIA (celdas de fuego, rutas, orígenes y puntos de encuentro) */
  lucia?: LuciaCollection;
  /** Equipos y operarios de JULI */
  juli?: JuliCollection;
  setBase: (url: string) => boolean;
  set: (patch: Partial<Omit<BackendState, 'setBase' | 'set'>>) => void;
}

export const useBackend = create<BackendState>()((set) => ({
  base: typeof window === 'undefined' ? '' : initialApiBase(),
  status: 'apagado',
  socket: false,
  setBase: (url) => {
    const base = normalizeBase(url);
    if (base && !validBase(base)) return false;
    saveApiBase(base);
    set({
      base,
      status: base ? 'conectando' : 'apagado',
      lucia: undefined,
      juli: undefined,
      socket: false,
    });
    return true;
  },
  set: (patch) => set(patch),
}));

/** Cada cuánto se comprueba que el backend sigue vivo */
const HEALTH_MS = 30_000;

interface Health {
  status: string;
  database?: string;
}

/**
 * Vigila /health del backend al poner la URL y cada 30 s. Va en el shell (no en el mapa) para
 * que el briefing y el chip de procedencia lo sepan desde el primer momento.
 */
export function useBackendHealth() {
  const base = useBackend((s) => s.base);
  useEffect(() => {
    const store = useBackend.getState();
    if (!base) {
      store.set({ status: 'apagado' });
      return;
    }
    let alive = true;
    const check = async () => {
      try {
        const health = await apiGet<Health>(base, '/health', 5000);
        const liveStatus = await apiGet<LiveStatus>(base, '/api/live/status', 5000).catch(
          () => undefined,
        );
        if (alive)
          useBackend.getState().set({
            status: 'conectado',
            database: health.database,
            live: liveStatus,
          });
      } catch {
        if (alive) useBackend.getState().set({ status: 'sin-conexion', socket: false });
      }
    };
    if (useBackend.getState().status === 'apagado') store.set({ status: 'conectando' });
    void check();
    const id = window.setInterval(check, HEALTH_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [base]);
}
