import { useT } from '../lib/i18n.ts';
import { Box, Square } from 'lucide-react';
import { useEffect } from 'react';
import { cn } from '../lib/cn.ts';
import { useUi, type MapMode } from '../store/ui.ts';

const MODES: [MapMode, string, typeof Square, string][] = [
  ['2d', '2D', Square, 'Plano cenital para coordinar'],
  ['3d', '3D', Box, 'Relieve; inclinándolo, vista 2.5D'],
];

/** Conmutador de modo de mapa, siempre visible. Atajos: 1 y 2. */
export function ModeSwitch() {
  const mode = useUi((s) => s.mapMode);
  const setMode = useUi((s) => s.setMapMode);
  const t = useT();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.ctrlKey || e.metaKey || e.altKey || /INPUT|SELECT|TEXTAREA/.test(target.tagName))
        return;
      // Con un diálogo abierto (briefing, metodología) el mapa no está a la vista: sin atajos
      if (document.querySelector('dialog[open]') || target.isContentEditable) return;
      if (e.key === '1') setMode('2d');
      if (e.key === '2') setMode('3d');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setMode]);

  return (
    <div
      role="radiogroup"
      aria-label={t('Modo del mapa')}
      className="flex rounded-md border border-line-strong bg-canvas p-0.5"
    >
      {MODES.map(([id, label, Icon, hint], i) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={mode === id}
          title={t('{hint} (tecla {n})', { hint: t(hint), n: i + 1 })}
          onClick={() => setMode(id)}
          className={cn(
            'flex h-8 cursor-pointer items-center gap-1.5 rounded-sm px-3 text-sm font-semibold pointer-coarse:h-10',
            mode === id
              ? 'bg-accent text-on-accent'
              : 'text-ink-muted hover:bg-hover hover:text-ink',
          )}
        >
          <Icon size={16} strokeWidth={1.75} aria-hidden className="max-sm:hidden" />
          {label}
        </button>
      ))}
    </div>
  );
}
