import { lazy, Suspense } from 'react';
import { useUi } from '../store/ui.ts';
import { ErrorBoundary } from './ErrorBoundary.tsx';

// MapLibre (~1 MB) va en un chunk aparte. En la primera visita se descarga al cerrar el
// briefing: mientras se lee, la página queda ligera (rendimiento y Lighthouse). En las
// siguientes visitas, sin briefing, el mapa carga directamente. Nunca hace falta un botón.
const MapView = lazy(() => import('../map/MapView.tsx'));

function Placeholder({ text }: { text: string }) {
  return (
    <p role="status" className="map-placeholder absolute inset-0 m-0 grid place-items-center">
      <span className="rounded-sm bg-canvas px-3 py-1.5">{text}</span>
    </p>
  );
}

export function MapStage() {
  const briefingOpen = useUi((s) => s.briefingOpen);
  return (
    <section aria-label="Mapa" className="relative min-h-48 flex-1">
      {briefingOpen ? (
        <Placeholder text="El mapa se carga al empezar" />
      ) : (
        <ErrorBoundary what="el mapa">
          <Suspense fallback={<Placeholder text="Cargando el mapa…" />}>
            <MapView />
          </Suspense>
        </ErrorBoundary>
      )}
    </section>
  );
}
