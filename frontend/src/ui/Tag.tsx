import type { ReactNode } from 'react';
import { cn } from '../lib/cn.ts';

type Tone = 'real' | 'simulado' | 'neutral' | 'aviso';

const tones: Record<Tone, string> = {
  real: 'border-ok/60 text-ok',
  simulado: 'border-warn/60 text-warn',
  aviso: 'border-warn/60 text-warn',
  neutral: 'border-line-strong text-ink-muted',
};

/** Rótulo de origen o estado. Siempre lleva texto: nunca depende solo del color. */
export function Tag({
  tone = 'neutral',
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center gap-1.5 rounded-sm border bg-surface px-2 text-xs font-semibold tracking-wide whitespace-nowrap uppercase',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
