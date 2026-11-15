import { useT } from '../lib/i18n.ts';
import { RotateCw, TriangleAlert } from 'lucide-react';
import { Button } from './Button.tsx';

/** Aviso de descarga fallida con botón para reintentar. Nunca se confunde con «no hay datos». */
export function LoadError({ what, onRetry }: { what: string; onRetry: () => void }) {
  const t = useT();
  return (
    <div role="alert" className="flex flex-col items-start gap-2 text-sm">
      <p className="m-0 flex items-start gap-2">
        <TriangleAlert
          size={16}
          strokeWidth={1.5}
          aria-hidden
          className="mt-0.5 shrink-0 text-warn"
        />
        {t('No se han podido descargar {what}. Comprueba la conexión.', { what: t(what) })}
      </p>
      <Button onClick={onRetry}>
        <RotateCw size={16} strokeWidth={1.5} aria-hidden />
        {t('Reintentar')}
      </Button>
    </div>
  );
}
