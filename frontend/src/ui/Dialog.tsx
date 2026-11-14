import * as RadixDialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn.ts';
import { Button } from './Button.tsx';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
  className?: string;
}

/** Diálogo modal único: foco atrapado, Esc y X para cerrar. */
export function Dialog({ open, onOpenChange, title, description, children, className }: Props) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-(--z-overlay) bg-black/70" />
        <RadixDialog.Content
          className={cn(
            'fixed top-1/2 left-1/2 z-(--z-dialog) flex max-h-[90dvh] w-[min(94vw,40rem)] max-w-[calc(100vw-16px)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-lg border border-line-strong bg-surface shadow-panel',
            className,
          )}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div className="min-w-0 flex-1">
              <RadixDialog.Title className="m-0 text-lg font-semibold">{title}</RadixDialog.Title>
              <RadixDialog.Description className="m-0 mt-1 text-sm text-ink-muted">
                {description}
              </RadixDialog.Description>
            </div>
            <RadixDialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Cerrar">
                <X size={20} strokeWidth={1.5} aria-hidden />
              </Button>
            </RadixDialog.Close>
          </header>
          <div className="min-h-0 overflow-y-auto px-5 py-4">{children}</div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
