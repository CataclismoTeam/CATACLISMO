import { CircleHelp, WifiOff } from 'lucide-react';
import { useEffect, useState } from 'react';
import { dataSource } from '../data/source.ts';
import { useHistory } from '../store/history.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { Tag } from '../ui/Tag.tsx';
import { Logo } from './Logo.tsx';
import { ModeSwitch } from './ModeSwitch.tsx';
import { RadioButton, RadioPanel } from './RadioPanel.tsx';
import { SettingsButton, SettingsPanel } from './SettingsPanel.tsx';

function UtcClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const iso = now.toISOString();
  return (
    <time
      dateTime={iso}
      data-dinamico
      className="hidden font-mono text-sm text-ink-muted xl:block"
      title="Fecha y hora en tiempo universal coordinado"
    >
      {iso.slice(0, 10)} {iso.slice(11, 19)} UTC
    </time>
  );
}

export function TopBar() {
  const lastDate = useHistory((s) => s.manifest?.tiempo.ultimoDato);
  const openBriefing = useUi((s) => s.openBriefing);

  return (
    <header className="relative z-(--z-bar) flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-3">
      <Logo />
      <div className="hidden min-w-0 flex-col leading-tight sm:flex">
        <h1 className="m-0 text-base font-bold tracking-[0.14em]">CATACLISMO</h1>
        <p className="m-0 hidden truncate text-xs text-ink-muted lg:block">
          Plataforma de mando para emergencias
        </p>
      </div>
      <h1 className="sr-only sm:hidden">CATACLISMO</h1>

      <ModeSwitch />

      <div className="ml-auto flex items-center gap-1.5">
        {lastDate && (
          <Tag tone="real" className="hidden lg:inline-flex">
            Real · FIRMS · hasta {lastDate}
          </Tag>
        )}
        <Tag className="hidden 2xl:inline-flex">
          <WifiOff size={14} strokeWidth={1.5} aria-hidden />
          {dataSource.label}
        </Tag>
        <UtcClock />
        <RadioButton />
        <SettingsButton />
        <Button
          variant="ghost"
          size="icon"
          aria-label="Qué es CATACLISMO"
          title="Qué es CATACLISMO"
          onClick={openBriefing}
        >
          <CircleHelp size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </div>
      <RadioPanel />
      <SettingsPanel />
    </header>
  );
}
