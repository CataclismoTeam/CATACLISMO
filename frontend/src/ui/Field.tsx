import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react';
import { cn } from '../lib/cn.ts';

const control =
  'h-9 w-full min-w-0 rounded-md border border-line-strong bg-canvas px-2.5 text-sm text-ink placeholder:text-ink-muted aria-invalid:border-fire pointer-coarse:h-11';

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="text-ink-muted">
        {label}
        {hint && <span className="ml-1 text-xs">({hint})</span>}
      </span>
      {children}
    </label>
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(control, 'font-mono', className)} {...props} />;
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(control, className)} {...props} />;
}
