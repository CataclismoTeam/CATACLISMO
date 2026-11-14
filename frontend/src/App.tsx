import { lazy, Suspense, useState } from 'react';

// Cesium pesa varios MB: se carga solo cuando se abre el globo, para que la portada
// sea ligera (Lighthouse y presupuesto de peso del CI).
const Globe = lazy(() => import('./components/Globe.tsx'));

export default function App() {
  const [showGlobe, setShowGlobe] = useState(false);

  return (
    <main className="app">
      <header className="header">
        <h1>CATACLISMO</h1>
        <p>Plantilla del proyecto para NASA Space Apps 2026.</p>
        {!showGlobe && (
          <button type="button" onClick={() => setShowGlobe(true)}>
            Abrir globo 3D
          </button>
        )}
      </header>
      {showGlobe && (
        <Suspense fallback={<p className="loading">Cargando globo…</p>}>
          <Globe />
        </Suspense>
      )}
    </main>
  );
}
