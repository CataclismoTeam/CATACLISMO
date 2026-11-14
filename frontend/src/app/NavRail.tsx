import { Flame, Mountain, Truck, Wind, type LucideIcon } from 'lucide-react';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';

interface Module {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Si existe, el botón abre y cierra su panel; si no, el módulo aún no está construido */
  panel?: 'incendios' | 'unidades';
}

// Registro de módulos. Los que aún no están construidos se ven desactivados y dicen por qué.
const MODULES: Module[] = [
  { id: 'incendios', label: 'Incendios', icon: Flame, panel: 'incendios' },
  { id: 'unidades', label: 'Unidades', icon: Truck, panel: 'unidades' },
  { id: 'entorno', label: 'Entorno', icon: Wind },
  { id: 'terreno', label: 'Terreno', icon: Mountain },
];

export function NavRail() {
  const leftPanel = useUi((s) => s.leftPanel);
  const setLeftPanel = useUi((s) => s.setLeftPanel);

  return (
    <nav
      aria-label="Módulos"
      className="order-last flex shrink-0 gap-1 border-t border-line bg-surface p-1.5 pb-[max(0.375rem,env(safe-area-inset-bottom))] lg:order-first lg:w-21 lg:flex-col lg:border-t-0 lg:border-r lg:pb-1.5"
    >
      {MODULES.map(({ id, label, icon: Icon, panel }) => {
        const open = !!panel && leftPanel === panel;
        return (
          <button
            key={id}
            type="button"
            aria-pressed={panel ? open : undefined}
            aria-disabled={!panel}
            title={
              panel
                ? `${open ? 'Cerrar' : 'Abrir'} ${label.toLowerCase()}`
                : `${label}: disponible en una próxima versión`
            }
            onClick={panel ? () => setLeftPanel(open ? null : panel) : undefined}
            className={cn(
              'h-14 flex-1 flex-col items-center justify-center gap-1 rounded-md border text-xs lg:flex-none',
              panel ? 'flex' : 'hidden lg:flex',
              panel
                ? 'cursor-pointer text-ink hover:bg-hover'
                : 'cursor-not-allowed border-transparent text-ink-muted opacity-60',
              open ? 'border-line-strong bg-hover' : 'border-transparent',
            )}
          >
            <Icon size={20} strokeWidth={1.5} aria-hidden />
            {label}
          </button>
        );
      })}
    </nav>
  );
}
