import { useCallback, useEffect, useState } from 'react';

/** Dato descargado con sus tres estados: así un fallo de red no se confunde con «no hay datos». */
export type Remote<T> =
  { status: 'cargando' } | { status: 'listo'; data: T } | { status: 'error'; retry: () => void };

/** Descarga `load` al montar y permite reintentar tras un fallo. */
export function useRemote<T>(load: () => Promise<T>): Remote<T> {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<Remote<T>>({ status: 'cargando' });
  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    setState({ status: 'cargando' });
    load().then(
      (data) => alive && setState({ status: 'listo', data }),
      () => alive && setState({ status: 'error', retry }),
    );
    return () => {
      alive = false;
    };
    // `load` es una función de módulo estable: solo se repite al reintentar
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  return state;
}

/** El dato si ya está listo. */
export const ready = <T>(r: Remote<T>): T | undefined =>
  r.status === 'listo' ? r.data : undefined;
