import { X } from 'lucide-react';
import { useEffect, useId, useRef, type ReactNode } from 'react';
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

/**
 * Diálogo modal con el <dialog> nativo: el navegador da el modo modal, el foco atrapado, el fondo
 * inerte y el cierre con Esc. Pesa casi nada, así que puede ir en el bundle inicial (el briefing
 * es lo primero que se ve). Misma interfaz que Dialog (Radix), que se usa en lo cargado después.
 */
export function ModalDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onClose={() => onOpenChange(false)}
      // Pulsar fuera del recuadro (en el fondo) cierra, como en el resto de diálogos
      onClick={(e) => e.target === e.currentTarget && onOpenChange(false)}
      className={cn(
        'm-auto max-h-[90dvh] w-[min(94vw,40rem)] max-w-[calc(100vw-16px)] flex-col rounded-lg border border-line-strong bg-surface p-0 text-ink shadow-panel backdrop:bg-black/70 open:flex',
        className,
      )}
    >
      <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="m-0 text-lg font-semibold">
            {title}
          </h2>
          <p id={descriptionId} className="m-0 mt-1 text-sm text-ink-muted">
            {description}
          </p>
        </div>
        <Button variant="ghost" size="icon" aria-label="Cerrar" onClick={() => onOpenChange(false)}>
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>
      <div className="min-h-0 overflow-y-auto px-5 py-4">{children}</div>
    </dialog>
  );
}
