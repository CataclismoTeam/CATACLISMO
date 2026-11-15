import { useEffect, useRef, type RefObject } from 'react';

/**
 * Comportamiento común de los paneles flotantes: al abrir lleva el foco al panel, se cierra con
 * Esc o con un clic fuera (ni en el panel ni en su botón) y al cerrar devuelve el foco al botón.
 */
export function usePopover(
  open: boolean,
  close: () => void,
  panel: RefObject<HTMLElement | null>,
  trigger?: RefObject<HTMLElement | null>,
) {
  const closeRef = useRef(close);
  useEffect(() => {
    closeRef.current = close;
  });

  useEffect(() => {
    if (!open) return;
    const returnTo = (trigger?.current ?? document.activeElement) as HTMLElement | null;
    const el = panel.current;
    el?.focus({ preventScroll: true });

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        closeRef.current();
      }
    };
    const onPointer = (e: PointerEvent) => {
      const target = e.target as Node;
      if (el?.contains(target) || returnTo?.contains(target)) return;
      closeRef.current();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
      // Solo devuelve el foco si seguía dentro del panel (no roba el foco a otro control)
      const active = document.activeElement;
      if (!active || active === document.body || el?.contains(active)) {
        returnTo?.focus({ preventScroll: true });
      }
    };
  }, [open, panel, trigger]);
}
