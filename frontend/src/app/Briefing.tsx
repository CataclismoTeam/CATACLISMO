import { ArrowRight } from 'lucide-react';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { Dialog } from '../ui/Dialog.tsx';
import { Tag } from '../ui/Tag.tsx';

/** Briefing inicial: qué es, para quién y por dónde empezar. Se puede volver a abrir con "?". */
export default function Briefing() {
  const open = useUi((s) => s.briefingOpen);
  const close = useUi((s) => s.closeBriefing);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && close()}
      title="CATACLISMO"
      description={`Plataforma de mando para emergencias · NASA Space Apps 2026 · front v${__APP_VERSION__.split('.')[0]}`}
    >
      <ul className="m-0 flex list-none flex-col gap-3 p-0 text-base">
        <li>
          <strong>Para quién:</strong> equipos de emergencias, gestores del territorio y personal
          científico.
        </li>
        <li>
          <strong>Mapa de mando:</strong> incendio, propagación prevista, unidades y vías de escape
          sobre el relieve (escenario simulado en Sierra Bermeja, Málaga).
        </li>
        <li>
          <strong>Histórico:</strong> elige un área y ve, mes a mes desde 2012, cuánto ha ardido y
          si este mes se sale de lo normal.
        </li>
        <li>
          <strong>Con qué datos:</strong> detecciones de fuego de los satélites MODIS y VIIRS,
          unificadas en una sola serie.
        </li>
      </ul>
      <div className="mt-4 flex flex-wrap gap-2">
        <Tag tone="real">Real · NASA FIRMS</Tag>
        <Tag tone="simulado">Escenario simulado</Tag>
        <Tag>Demo · sin conexión a backend</Tag>
      </div>
      <div className="mt-6 flex flex-wrap gap-3">
        <Button variant="primary" size="lg" onClick={close}>
          <ArrowRight size={20} strokeWidth={1.5} aria-hidden />
          Empezar
        </Button>
      </div>
    </Dialog>
  );
}
