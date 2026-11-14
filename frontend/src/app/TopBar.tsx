import { CircleHelp, Presentation, WifiOff } from 'lucide-react';
import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { dataSource } from '../data/source.ts';
import { useHistory } from '../store/history.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { Tag } from '../ui/Tag.tsx';
import { Logo } from './Logo.tsx';

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
      className="hidden font-mono text-sm text-ink-muted lg:block"
      title="Fecha y hora en tiempo universal coordinado"
    >
      {iso.slice(0, 10)} {iso.slice(11, 19)} UTC
    </time>
  );
}

export function TopBar() {
  const lastDate = useHistory((s) => s.manifest?.tiempo.ultimoDato);
  const projection = useUi((s) => s.projection);
  const toggleProjection = useUi((s) => s.toggleProjection);
  const openBriefing = useUi((s) => s.openBriefing);

  return (
    <motion.header
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="z-(--z-bar) flex h-14 shrink-0 items-center gap-4 border-b border-white/8 bg-[#0d1219]/95 px-4 backdrop-blur-md"
    >
      <Logo />
      <div className="flex min-w-0 items-baseline gap-2.5">
        <h1 className="m-0 text-sm font-bold tracking-[0.18em]">CATACLISMO</h1>
        <p className="m-0 hidden truncate text-sm text-ink-muted md:block">
          Plataforma de mando para emergencias
        </p>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <span className="hidden items-center gap-2 rounded-full border border-ok/20 bg-ok/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-ok lg:flex">
          <span className="size-1.5 rounded-full bg-ok" />
          Sistema operativo
        </span>
        {lastDate && (
          <Tag tone="real" className="hidden sm:inline-flex">
            Real · FIRMS · hasta {lastDate}
          </Tag>
        )}
        <Tag className="hidden md:inline-flex">
          <WifiOff size={14} strokeWidth={1.5} aria-hidden />
          {dataSource.label}
        </Tag>
        <UtcClock />
        <Button
          variant="ghost"
          size="icon"
          aria-pressed={projection}
          aria-label="Modo proyección: texto grande"
          title="Modo proyección: texto grande"
          onClick={toggleProjection}
        >
          <Presentation size={20} strokeWidth={1.5} aria-hidden />
        </Button>
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
    </motion.header>
  );
}
