import { t } from '../lib/i18n.ts';
import { ExternalLink } from 'lucide-react';
import { cn } from '../lib/cn.ts';
import type { Source } from '../lib/sources.ts';

/** Enlace a una fuente de datos, en otra pestaña. */
export function SourceLink({ source, className }: { source: Source; className?: string }) {
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        'inline-flex items-center gap-1 text-accent underline-offset-2 hover:underline',
        className,
      )}
    >
      {source.name}
      <ExternalLink size={12} strokeWidth={1.5} aria-hidden />
      <span className="sr-only">{t('(se abre en otra pestaña)')}</span>
    </a>
  );
}
