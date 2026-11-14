import { Flame, Truck } from 'lucide-react';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';

/** Accesos a los paneles izquierdos cuando no hay ninguno abierto (siempre visibles en móvil). */
export function LeftToolbar() {
  const leftPanel = useUi((s) => s.leftPanel);
  const setLeftPanel = useUi((s) => s.setLeftPanel);
  if (leftPanel) return null;
  return (
    <div className="absolute top-3 left-3 flex gap-2">
      <Button onClick={() => setLeftPanel('incendios')}>
        <Flame size={16} strokeWidth={1.5} aria-hidden />
        Incendios
      </Button>
      <Button onClick={() => setLeftPanel('unidades')}>
        <Truck size={16} strokeWidth={1.5} aria-hidden />
        Unidades
      </Button>
    </div>
  );
}
