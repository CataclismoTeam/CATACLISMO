import { lazy, Suspense, useEffect, useState } from 'react';
import { CalendarDock } from '../features/history/CalendarDock.tsx';
import { useHistory } from '../store/history.ts';
import { useUi } from '../store/ui.ts';
import { MapStage } from './MapStage.tsx';
import { NavRail } from './NavRail.tsx';
import { TopBar } from './TopBar.tsx';

// El briefing (y con él la librería de diálogos) solo se descarga si hay que mostrarlo
const Briefing = lazy(() => import('./Briefing.tsx'));

export function Shell() {
  const load = useHistory((s) => s.load);
  const projection = useUi((s) => s.projection);
  const briefingOpen = useUi((s) => s.briefingOpen);
  // Una vez cargado, el briefing queda montado: desmontarlo de golpe al cerrarlo dejaba
  // el resto de la página oculta para los lectores de pantalla (aria-hidden de Radix)
  const [briefingLoaded, setBriefingLoaded] = useState(briefingOpen);
  if (briefingOpen && !briefingLoaded) setBriefingLoaded(true);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    document.documentElement.dataset.projection = String(projection);
  }, [projection]);

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <NavRail />
        <main className="flex min-w-0 flex-1 flex-col">
          <MapStage />
          <CalendarDock />
        </main>
      </div>
      {briefingLoaded && (
        <Suspense fallback={null}>
          <Briefing />
        </Suspense>
      )}
    </div>
  );
}
