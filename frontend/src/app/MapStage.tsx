import { useT } from '../lib/i18n.ts';
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
  const t = useT();
  return (
    <section
      id="mapa-principal"
      tabIndex={-1}
      aria-label={t('Mapa')}
      className="relative min-h-48 flex-1 outline-none"
    >
      {briefingOpen ? (
        <Placeholder text={t('El mapa se carga al empezar')} />
      ) : (
        <ErrorBoundary what={t('el mapa')}>
          <Suspense fallback={<Placeholder text={t('Cargando el mapa…')} />}>
            <MapView />
          </Suspense>
        </ErrorBoundary>
      )}
    </section>
  );
}
