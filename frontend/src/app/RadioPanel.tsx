import { Mic, Radio, X } from 'lucide-react';
import { useState } from 'react';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { Tag } from '../ui/Tag.tsx';

// Canales de la demo (SIMULADOS). La voz real llegará con el backend (WebSocket /ws).
const CHANNELS = [
  {
    id: 'mando',
    name: 'Mando y control',
    freq: 'TETRA · GSSI 4101',
    last: 'PMA-1: sector norte estabilizado',
  },
  {
    id: 'tactico',
    name: 'Táctico extinción',
    freq: 'TETRA · GSSI 4102',
    last: 'AB-EST-12: abastecimiento en Los Reales',
  },
  {
    id: 'aereo',
    name: 'Coordinación aérea',
    freq: 'VHF 123,450 MHz',
    last: 'BRIF-RO-1: descarga en cabeza del fuego',
  },
  {
    id: 'sanitario',
    name: 'Sanitario',
    freq: 'TETRA · GSSI 4105',
    last: 'SVA-EST: sin incidencias',
  },
];

export function RadioButton() {
  const open = useUi((s) => s.radioOpen);
  const setOpen = useUi((s) => s.setRadioOpen);
  return (
    <Button
      variant={open ? 'secondary' : 'ghost'}
      aria-pressed={open}
      aria-label="Radio"
      title="Radio: canales del operativo"
      onClick={() => setOpen(!open)}
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
  const [channel, setChannel] = useState(CHANNELS[0].id);
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
      <ul role="radiogroup" aria-label="Canal" className="m-0 flex list-none flex-col gap-1 p-2">
        {CHANNELS.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              role="radio"
              aria-checked={channel === c.id}
              onClick={() => setChannel(c.id)}
              className={cn(
                'flex w-full cursor-pointer flex-col gap-0.5 rounded-md border px-3 py-2 text-left text-sm',
                channel === c.id ? 'border-accent bg-hover' : 'border-transparent hover:bg-hover',
              )}
            >
              <span className="flex justify-between gap-2 font-semibold">
                {c.name}
                <span className="font-mono text-xs font-normal text-ink-muted">{c.freq}</span>
              </span>
              <span className="text-ink-muted">{c.last}</span>
            </button>
          </li>
        ))}
      </ul>
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
