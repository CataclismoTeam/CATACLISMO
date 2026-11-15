import { useT } from '../lib/i18n.ts';
import { CircleHelp } from 'lucide-react';
import { lazy, Suspense, useEffect, useState } from 'react';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { Logo } from './Logo.tsx';
import { ModeSwitch } from './ModeSwitch.tsx';
import { Provenance } from './Provenance.tsx';
import { LanguageButton, RadioButton, SettingsButton } from './TopBarButtons.tsx';

// Los paneles de radio y ajustes solo se descargan al abrirlos
const RadioPanel = lazy(() => import('./RadioPanel.tsx').then((m) => ({ default: m.RadioPanel })));
const SettingsPanel = lazy(() =>
  import('./SettingsPanel.tsx').then((m) => ({ default: m.SettingsPanel })),
);

function UtcClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const iso = now.toISOString();
  const t = useT();
  return (
    <time
      dateTime={iso}
      data-dinamico
      className="hidden font-mono text-sm text-ink-muted xl:block"
      title={t('Fecha y hora en tiempo universal coordinado')}
    >
      {iso.slice(0, 10)} {iso.slice(11, 19)} UTC
    </time>
  );
}

export function TopBar() {
  const openBriefing = useUi((s) => s.openBriefing);
  const radioOpen = useUi((s) => s.radioOpen);
  const settingsOpen = useUi((s) => s.settingsOpen);
  const t = useT();

  return (
    <header className="relative z-(--z-bar) flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-2 sm:px-3 md:gap-3">
      <Logo />
      <div className="hidden min-w-0 flex-col leading-tight sm:flex">
        <h1 className="m-0 text-base font-bold tracking-[0.14em]">CATACLISMO</h1>
        <p className="m-0 hidden truncate text-xs text-ink-muted lg:block">
          {t('Plataforma de mando para emergencias')}
        </p>
      </div>
      <h1 className="sr-only sm:hidden">CATACLISMO</h1>

      <ModeSwitch />
      {/* Hueco del buscador: lo rellena el mapa al cargarse (va en su chunk, no en el inicial) */}
      <div id="buscador-barra" className="hidden min-w-0 flex-1 justify-center lg:flex" />

      <div className="ml-auto flex items-center gap-1.5">
        <Provenance />
        <UtcClock />
        <LanguageButton className="max-sm:hidden" />
        <RadioButton />
        <SettingsButton />
        <Button
          variant="ghost"
          size="icon"
          aria-label={t('Qué es CATACLISMO')}
          title={t('Qué es CATACLISMO')}
          onClick={openBriefing}
        >
          <CircleHelp size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </div>
      <Suspense fallback={null}>
        {radioOpen && <RadioPanel />}
        {settingsOpen && <SettingsPanel />}
      </Suspense>
    </header>
  );
}
