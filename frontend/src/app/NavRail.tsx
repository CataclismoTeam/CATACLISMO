import { CalendarDays, Flame, Mountain, Truck, Wind, type LucideIcon } from 'lucide-react';
import { cn } from '../lib/cn.ts';

interface Module {
  id: string;
  label: string;
  icon: LucideIcon;
  ready: boolean;
}

// Registro de módulos. Los que aún no están construidos se ven desactivados y dicen por qué.
const MODULES: Module[] = [
  { id: 'incidentes', label: 'Incendios', icon: Flame, ready: true },
  { id: 'historico', label: 'Histórico', icon: CalendarDays, ready: true },
  { id: 'unidades', label: 'Unidades', icon: Truck, ready: false },
  { id: 'entorno', label: 'Entorno', icon: Wind, ready: false },
  { id: 'terreno', label: 'Terreno', icon: Mountain, ready: false },
];

export function NavRail() {
  return (
    <nav
      aria-label="Módulos"
      className="hidden w-21 shrink-0 flex-col gap-1 border-r border-line bg-surface p-1.5 lg:flex"
    >
      {MODULES.map(({ id, label, icon: Icon, ready }) => (
        <button
          key={id}
          type="button"
          aria-disabled={!ready}
          title={ready ? label : `${label}: disponible en una próxima versión`}
          className={cn(
            'flex h-14 flex-col items-center justify-center gap-1 rounded-md border border-transparent text-xs',
            ready ? 'cursor-default text-ink' : 'cursor-not-allowed text-ink-muted opacity-60',
          )}
        >
          <Icon size={20} strokeWidth={1.5} aria-hidden />
          {label}
        </button>
      ))}
    </nav>
  );
}
