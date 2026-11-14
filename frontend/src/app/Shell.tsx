import { useEffect } from 'react';
import { CalendarDock } from '../features/history/CalendarDock.tsx';
import { useHistory } from '../store/history.ts';
import { useUi } from '../store/ui.ts';
import { Briefing } from './Briefing.tsx';
import { MapStage } from './MapStage.tsx';
import { NavRail } from './NavRail.tsx';
import { TopBar } from './TopBar.tsx';

// El briefing (y con él la librería de diálogos) solo se descarga si hay que mostrarlo

export function Shell() {
  const load = useHistory((s) => s.load);
  const projection = useUi((s) => s.projection);
  const briefingOpen = useUi((s) => s.briefingOpen);

  useEffect(() => {
    void load();
  }, [load]);

  // La rejilla del histórico se pide al cerrar el briefing (en visitas siguientes, al entrar)
  const ensureGrid = useHistory((s) => s.ensureGrid);
  useEffect(() => {
    if (!briefingOpen) void ensureGrid();
  }, [briefingOpen, ensureGrid]);

  useEffect(() => {
    document.documentElement.dataset.projection = String(projection);
  }, [projection]);

  // Tema: "sistema" sigue la preferencia del sistema operativo y cambia en vivo
  const theme = useUi((s) => s.theme);
  const cvd = useUi((s) => s.cvd);
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: light)');
    const apply = () => {
      const light = theme === 'claro' || (theme === 'sistema' && media.matches);
      document.documentElement.dataset.theme = light ? 'claro' : 'oscuro';
    };
    apply();
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [theme]);
  useEffect(() => {
    document.documentElement.dataset.cvd = cvd;
  }, [cvd]);

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
      <Briefing />
    </div>
  );
}
