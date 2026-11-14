import { Flame, Mountain, Truck, Wind, type LucideIcon } from 'lucide-react';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';

interface Module {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Si existe, el botón abre y cierra su panel; si no, el módulo aún no está construido */
  panel?: 'incendios';
}

// Registro de módulos. Los que aún no están construidos se ven desactivados y dicen por qué.
const MODULES: Module[] = [
  { id: 'incendios', label: 'Incendios', icon: Flame, panel: 'incendios' },
  { id: 'unidades', label: 'Unidades', icon: Truck },
  { id: 'entorno', label: 'Entorno', icon: Wind },
  { id: 'terreno', label: 'Terreno', icon: Mountain },
];

export function NavRail() {
  const incidentsOpen = useUi((s) => s.incidentsOpen);
  const setIncidentsOpen = useUi((s) => s.setIncidentsOpen);

  return (
    <nav
      aria-label="Módulos"
      className="hidden w-21 shrink-0 flex-col gap-1 border-r border-line bg-surface p-1.5 lg:flex"
    >
      {MODULES.map(({ id, label, icon: Icon, panel }) => {
        const open = panel === 'incendios' && incidentsOpen;
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
            onClick={panel ? () => setIncidentsOpen(!incidentsOpen) : undefined}
            className={cn(
              'flex h-14 flex-col items-center justify-center gap-1 rounded-md border text-xs',
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
