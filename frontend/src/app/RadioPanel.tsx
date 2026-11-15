import { Mic, Radio, X } from 'lucide-react';
import { useState } from 'react';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { Tag } from '../ui/Tag.tsx';
import { channelsFor, DOMAIN_LABEL, SCENARIOS, type Domain } from '../map/scenario.ts';

// Canales de la simulación activa (SIMULADOS). La voz real llegará con el backend (WebSocket /ws).

export function RadioButton() {
  const open = useUi((s) => s.radioOpen);
  const setOpen = useUi((s) => s.setRadioOpen);
  return (
    <Button
      variant={open ? 'secondary' : 'ghost'}
      aria-pressed={open}
      aria-label="Radio"
      title="Radio: canales del operativo"
      onClick={() => {
        useUi.getState().setSettingsOpen(false);
        setOpen(!open);
      }}
      className="px-2.5"
    >
      <Radio size={20} strokeWidth={1.5} aria-hidden />
      <span className="hidden xl:inline">Radio</span>
    </Button>
  );
}

/** Panel de radio: canales del operativo y último mensaje de cada uno. */
export function RadioPanel() {
  const open = useUi((s) => s.radioOpen);
  const setOpen = useUi((s) => s.setRadioOpen);
  const scenario = SCENARIOS[useUi((s) => s.scenario)];
  const channels = scenario ? channelsFor(scenario) : [];
  const [picked, setChannel] = useState('tierra-general');
  const channel = channels.some((c) => c.id === picked) ? picked : channels[0]?.id;
  if (!open) return null;
  return (
    <aside
      aria-label="Radio"
      className="absolute top-14 right-2 z-(--z-overlay) w-[min(24rem,calc(100vw-1rem))] rounded-lg border border-line-strong bg-surface shadow-panel"
    >
      <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2">
        <h2 className="m-0 flex items-center gap-2 text-base font-semibold">
          <Radio size={20} strokeWidth={1.5} aria-hidden /> Radio
        </h2>
        <div className="flex items-center gap-2">
          <Tag tone="simulado">Simulado</Tag>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Cerrar radio"
            onClick={() => setOpen(false)}
          >
            <X size={20} strokeWidth={1.5} aria-hidden />
          </Button>
        </div>
      </header>
      <div role="radiogroup" aria-label="Canal" className="max-h-[60dvh] overflow-y-auto p-2">
        {(['aire', 'tierra'] as Domain[]).map((domain) => {
          const list = channels.filter((c) => c.domain === domain);
          if (!list.length) return null;
          return (
            <section key={domain} className="mb-1">
              <h3 className="m-0 px-2 py-1 text-xs font-semibold tracking-wide text-ink-muted uppercase">
                {DOMAIN_LABEL[domain]}
              </h3>
              {list.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  role="radio"
                  aria-checked={channel === c.id}
                  onClick={() => setChannel(c.id)}
                  className={cn(
                    'flex w-full cursor-pointer flex-col gap-0.5 rounded-md border px-3 py-2 text-left text-sm',
                    channel === c.id
                      ? 'border-accent bg-hover'
                      : 'border-transparent hover:bg-hover',
                    c.id.startsWith('tierra-') && c.id !== 'tierra-general' && 'pl-6',
                  )}
                >
                  <span className="flex justify-between gap-2 font-semibold">
                    {c.name}
                    <span className="text-xs font-normal text-ink-muted">
                      {c.members.length} {c.members.length === 1 ? 'medio' : 'medios'}
                    </span>
                  </span>
                  <span className="text-ink-muted">{c.last}</span>
                </button>
              ))}
            </section>
          );
        })}
      </div>
      <footer className="flex items-center gap-3 border-t border-line px-4 py-3">
        <Button disabled aria-describedby="radio-motivo">
          <Mic size={16} strokeWidth={1.5} aria-hidden />
          Pulsar para hablar
        </Button>
        <p id="radio-motivo" className="m-0 text-xs text-ink-muted">
          Próximamente: la voz necesita conexión con el servidor del operativo.
        </p>
      </footer>
    </aside>
  );
}
