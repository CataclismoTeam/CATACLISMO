import { useT } from '../lib/i18n.ts';
import { lazy, Suspense, useEffect } from 'react';
import { CalendarDock } from '../features/history/CalendarDock.tsx';
import { useHistory } from '../store/history.ts';
import { useUi } from '../store/ui.ts';
import { Briefing } from './Briefing.tsx';
import { MapStage } from './MapStage.tsx';
import { NavRail } from './NavRail.tsx';
import { TopBar } from './TopBar.tsx';

// La metodología (datos y métodos) solo se descarga al abrirla, desde el calendario o la procedencia
const MethodDialog = lazy(() => import('../features/history/MethodDialog.tsx'));

export function Shell() {
  const load = useHistory((s) => s.load);
  const projection = useUi((s) => s.projection);
  const briefingOpen = useUi((s) => s.briefingOpen);
  const methodOpen = useUi((s) => s.methodOpen);
  const t = useT();

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
      {/* Primer elemento con Tab: salta la barra y el rail directamente al mapa */}
      <a
        href="#mapa-principal"
        className="sr-only z-(--z-dialog) rounded-md bg-accent px-3 py-2 font-semibold text-on-accent focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
      >
        {t('Saltar al mapa')}
      </a>
      <TopBar />
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <NavRail />
        <main className="flex min-w-0 flex-1 flex-col">
          <MapStage />
          <CalendarDock />
        </main>
      </div>
      <Briefing />
      {methodOpen && (
        <Suspense fallback={null}>
          <MethodDialog />
        </Suspense>
      )}
    </div>
  );
}
