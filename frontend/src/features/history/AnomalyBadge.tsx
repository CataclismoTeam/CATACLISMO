import { useT } from '../../lib/i18n.ts';
import {
  ChevronDown,
  ChevronsUp,
  ChevronUp,
  CircleHelp,
  Minus,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '../../lib/cn.ts';
import { ANOMALY_LABEL, type AnomalyLevel } from './stats.ts';

// Cada nivel lleva icono y texto además del color: se entiende en escala de grises.
const STYLE: Record<AnomalyLevel, { icon: LucideIcon; className: string }> = {
  'muy por encima': { icon: ChevronsUp, className: 'border-fire text-fire' },
  'por encima': { icon: ChevronUp, className: 'border-warn text-warn' },
  normal: { icon: Minus, className: 'border-line-strong text-ink' },
  'por debajo': { icon: ChevronDown, className: 'border-water text-water' },
  'sin referencia': { icon: CircleHelp, className: 'border-line-strong text-ink-muted' },
};

export function AnomalyBadge({ level, large }: { level: AnomalyLevel; large?: boolean }) {
  const { icon: Icon, className } = STYLE[level];
  const t = useT();
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-sm border bg-surface font-semibold whitespace-nowrap',
        large ? 'h-8 px-2.5 text-base' : 'h-6 px-2 text-sm',
        className,
      )}
    >
      <Icon size={large ? 20 : 16} strokeWidth={2} aria-hidden />
      {t(ANOMALY_LABEL[level])}
    </span>
  );
}
