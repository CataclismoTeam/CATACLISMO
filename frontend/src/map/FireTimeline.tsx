import { Pause, Play } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { HORIZON_H } from './scenario.ts';

/** Ritmo de reproducción: las 6 h del modelo en unos 12 s. */
const HOURS_PER_SECOND = HORIZON_H / 12;

const hourLabel = (h: number) =>
  `T+${h.toLocaleString('es-ES', { maximumFractionDigits: 1, minimumFractionDigits: 0 })} h`;

const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * Línea de tiempo del incendio SIMULADO: reproduce o arrastra la hora desde la ignición. Lo que
 * llega antes de esa hora se pinta como ya ardido y lo posterior como predicción.
 */
export function FireTimeline() {
  const hour = useUi((s) => s.fireHour);
  const playing = useUi((s) => s.playing);
  const setHour = useUi((s) => s.setFireHour);
  const setPlaying = useUi((s) => s.setPlaying);
  // Hora con decimales completos mientras se reproduce; al store va redondeada a 0,1 h
  const exact = useRef(hour);

  useEffect(() => {
    if (!playing) return;
    exact.current = useUi.getState().fireHour;
    const advance = (dh: number) => {
      exact.current = Math.min(HORIZON_H, exact.current + dh);
      setHour(Math.round(exact.current * 10) / 10);
      if (exact.current >= HORIZON_H) setPlaying(false);
    };
    // Sin animación continua si el sistema pide menos movimiento: saltos de 1 h cada segundo
    if (reducedMotion()) {
      const id = window.setInterval(() => advance(1), 1000);
      return () => window.clearInterval(id);
    }
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      advance(((now - last) / 1000) * HOURS_PER_SECOND);
      last = now;
      if (exact.current < HORIZON_H) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, setHour, setPlaying]);

  const toggle = () => {
    // Al final, reproducir vuelve a empezar desde la ignición
    if (!playing && hour >= HORIZON_H) setHour(0);
    setPlaying(!playing);
  };

  return (
    <section
      aria-label="Línea de tiempo del incendio"
      className="flex w-88 max-w-full shrink-0 items-center gap-3 rounded-md border border-line-strong bg-surface px-3 py-2 shadow-panel"
    >
      <Button
        variant="ghost"
        size="icon"
        aria-label={playing ? 'Pausar' : 'Reproducir'}
        onClick={toggle}
      >
        {playing ? (
          <Pause size={20} strokeWidth={1.5} aria-hidden />
        ) : (
          <Play size={20} strokeWidth={1.5} aria-hidden />
        )}
      </Button>
      <label className="flex min-w-0 flex-1 flex-col gap-0.5 text-xs">
        <span className="flex items-baseline justify-between gap-2">
          <span className="text-ink-muted">Tiempo tras la ignición · simulado</span>
          <output className="font-mono text-sm font-semibold text-ink">{hourLabel(hour)}</output>
        </span>
        <input
          type="range"
          min={0}
          max={HORIZON_H}
          step={0.1}
          value={hour}
          aria-valuetext={hourLabel(hour)}
          onChange={(e) => {
            setPlaying(false);
            setHour(Number(e.target.value));
          }}
          className="w-full accent-accent pointer-coarse:h-11"
        />
      </label>
    </section>
  );
}
