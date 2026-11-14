import { lazy, Suspense } from 'react';
import { ErrorBoundary } from './ErrorBoundary.tsx';

// MapLibre va en un chunk aparte para que la primera pintura del shell sea ligera,
// pero se carga siempre: el mapa es la aplicación.
// La descarga empieza al cargar este módulo, en paralelo al primer render del shell
const mapModule = import('../map/MapView.tsx');
const MapView = lazy(() => mapModule);

export function MapStage() {
  return (
    <section aria-label="Mapa" className="relative min-h-48 flex-1">
      <ErrorBoundary what="el mapa">
        <Suspense
          fallback={
            <p
              role="status"
              className="map-placeholder absolute inset-0 m-0 grid place-items-center"
            >
              <span className="rounded-sm bg-canvas px-3 py-1.5">Cargando el mapa…</span>
            </p>
          }
        >
          <MapView />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}
