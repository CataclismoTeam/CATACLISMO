import type { Map as MapLibre } from 'maplibre-gl';
import { useEffect, type RefObject } from 'react';
import { formatHash } from '../lib/hash.ts';
import { useLang } from '../lib/i18n.ts';
import { useUi } from '../store/ui.ts';

/** Escribe el hash ya (lo usa «Copiar enlace»); null sin mapa */
let flush: (() => void) | null = null;

/**
 * Mantiene en el hash de la URL la vista actual (simulación, incendio, zoom, centro y modo) para
 * que «Copiar enlace» lleve exactamente a lo que se ve. Usa replaceState: no llena el historial.
 */
export function useShareHash(map: RefObject<MapLibre | null>, ready: boolean) {
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    let timer = 0;
    const writeNow = () => {
      window.clearTimeout(timer);
      const { scenario, selectedIncident, mapMode } = useUi.getState();
      const c = m.getCenter();
      const hash = formatHash({
        sim: scenario,
        inc: selectedIncident,
        zoom: m.getZoom(),
        center: [c.lng, c.lat],
        mode: mapMode,
        lang: useLang.getState().lang,
      });
      if (hash !== window.location.hash) {
        window.history.replaceState(
          null,
          '',
          `${window.location.pathname}${window.location.search}${hash}`,
        );
      }
    };
    const write = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(writeNow, 250);
    };
    flush = writeNow;
    m.on('moveend', write);
    const unsubscribe = useUi.subscribe((s, prev) => {
      if (
        s.scenario !== prev.scenario ||
        s.selectedIncident !== prev.selectedIncident ||
        s.mapMode !== prev.mapMode
      ) {
        write();
      }
    });
    const unsubscribeLang = useLang.subscribe(write);
    write();
    return () => {
      unsubscribeLang();
      window.clearTimeout(timer);
      flush = null;
      m.off('moveend', write);
      unsubscribe();
    };
  }, [map, ready]);
}

/** Copia la dirección actual (con su hash) al portapapeles. */
export async function copyLink(): Promise<boolean> {
  flush?.(); // el hash al día, sin esperar al retardo
  try {
    await navigator.clipboard.writeText(window.location.href);
    return true;
  } catch {
    return false;
  }
}
