import {
  CalendarDays,
  ChartColumn,
  Flame,
  Mountain,
  Radio,
  Truck,
  Wind,
  type LucideIcon,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../lib/cn.ts';

interface Module {
  id: string;
  label: string;
  icon: LucideIcon;
  ready: boolean;
}

// Registro de módulos. Los que aún no están construidos se ven desactivados y dicen por qué.
const MODULES: Module[] = [
  { id: 'operaciones', label: 'Operaciones', icon: Radio, ready: false },
  { id: 'incidentes', label: 'Incidentes', icon: Flame, ready: false },
  { id: 'unidades', label: 'Unidades', icon: Truck, ready: false },
  { id: 'entorno', label: 'Entorno', icon: Wind, ready: false },
  { id: 'terreno', label: 'Terreno', icon: Mountain, ready: false },
  { id: 'analisis', label: 'Análisis', icon: ChartColumn, ready: false },
  { id: 'historico', label: 'Histórico', icon: CalendarDays, ready: true },
];

export function NavRail() {
  return (
    <nav
      aria-label="Módulos"
      className="hidden w-24 shrink-0 flex-col gap-1 border-r border-white/8 bg-[#0d1219] p-2 md:flex"
    >
      <p className="mb-2 mt-1 px-2 text-[9px] font-semibold uppercase tracking-[0.18em] text-ink-muted">
        Módulos
      </p>
      {MODULES.map(({ id, label, icon: Icon, ready }) => (
        <motion.button
          whileHover={ready ? { x: 2 } : undefined}
          key={id}
          type="button"
          aria-current={ready ? 'page' : undefined}
          aria-disabled={!ready}
          title={ready ? label : `${label}: disponible en una próxima versión`}
          className={cn(
            'group relative flex h-14 flex-col items-center justify-center gap-1 rounded-lg border border-transparent text-[10px] transition-colors',
            ready
              ? 'cursor-default border-white/10 bg-white/6 text-ink'
              : 'cursor-not-allowed text-ink-muted opacity-50',
          )}
        >
          <Icon size={20} strokeWidth={1.5} aria-hidden />
          {label}
          <span
            className={cn(
              'absolute right-2 top-2 size-1.5 rounded-full',
              ready ? 'bg-ok' : 'bg-line-strong',
            )}
          />
        </motion.button>
      ))}
    </nav>
  );
}
