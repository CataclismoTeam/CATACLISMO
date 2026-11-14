import { Map as MapIcon } from 'lucide-react';
import { lazy, Suspense } from 'react';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { ErrorBoundary } from './ErrorBoundary.tsx';

// Cesium pesa varios MB: se descarga solo cuando se abre el mapa, para que la primera
// pantalla sea ligera (Lighthouse y presupuesto de peso del CI).
const Globe = lazy(() => import('../map/Globe.tsx'));

export function MapStage() {
  const mapOpen = useUi((s) => s.mapOpen);
  const openMap = useUi((s) => s.openMap);

  if (!mapOpen) {
    return (
      <section
        aria-label="Mapa"
        className="map-placeholder flex min-h-28 flex-1 flex-col items-center justify-center gap-3 p-4"
      >
        <Button onClick={openMap}>
          <MapIcon size={20} strokeWidth={1.5} aria-hidden />
          Abrir el mapa
        </Button>
        <p className="m-0 rounded-sm bg-canvas px-2 text-sm text-ink-muted">
          El mapa se descarga al abrirlo (unos 4 MB).
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Mapa" className="relative min-h-28 flex-1">
      <ErrorBoundary what="el mapa">
        <Suspense
          fallback={
            <p role="status" className="map-placeholder m-0 grid h-full place-items-center">
              <span className="rounded-sm bg-canvas px-2">Cargando el mapa…</span>
            </p>
          }
        >
          <Globe />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}
