import { useEnglish, useT } from '../lib/i18n.ts';
import { ArrowRight } from 'lucide-react';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { ModalDialog } from '../ui/ModalDialog.tsx';
import { Tag } from '../ui/Tag.tsx';
import { SOURCES } from '../lib/sources.ts';
import { SourceLink } from '../ui/SourceLink.tsx';

/** Briefing inicial: qué es, para quién y por dónde empezar. Se puede volver a abrir con "?". */
export function Briefing() {
  const open = useUi((s) => s.briefingOpen);
  const close = useUi((s) => s.closeBriefing);
  const t = useT();
  const en = useEnglish();

  return (
    <ModalDialog
      open={open}
      onOpenChange={(next) => !next && close()}
      title="CATACLISMO"
      description={`${t('Plataforma de mando para emergencias')} · NASA Space Apps 2026 · front v${__APP_VERSION__.split('.')[0]}`}
    >
      {en ? (
        <ul className="m-0 flex list-none flex-col gap-3 p-0 text-base">
          <li>
            <strong>For:</strong> emergency teams, land managers and scientists.
          </li>
          <li>
            <strong>Command map:</strong> fire, predicted spread, units, alerts and escape routes on
            the terrain (12 simulated scenarios across Spain).
          </li>
          <li>
            <strong>History:</strong> pick an area and see, month by month since 2012, how much has
            burned and whether this month is out of the ordinary.
          </li>
          <li>
            <strong>Data:</strong> fire detections from the <SourceLink source={SOURCES.modis} />{' '}
            and <SourceLink source={SOURCES.viirs} /> satellites via{' '}
            <SourceLink source={SOURCES.firms} />, merged into a single series. Anything simulated
            is always labelled as such.
          </li>
        </ul>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-3 p-0 text-base">
          <li>
            <strong>Para quién:</strong> equipos de emergencias, gestores del territorio y personal
            científico.
          </li>
          <li>
            <strong>Mapa de mando:</strong> incendio, propagación prevista, unidades, avisos y vías
            de escape sobre el relieve (12 escenarios simulados por España).
          </li>
          <li>
            <strong>Histórico:</strong> elige un área y ve, mes a mes desde 2012, cuánto ha ardido y
            si este mes se sale de lo normal.
          </li>
          <li>
            <strong>Con qué datos:</strong> detecciones de fuego de los satélites{' '}
            <SourceLink source={SOURCES.modis} /> y <SourceLink source={SOURCES.viirs} /> de{' '}
            <SourceLink source={SOURCES.firms} />, unificadas en una sola serie. Lo simulado se
            rotula siempre como tal.
          </li>
        </ul>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <Tag tone="real">{t('Real · NASA FIRMS')}</Tag>
        <Tag tone="simulado">{t('Escenario simulado')}</Tag>
      </div>
      <div className="mt-6 flex flex-wrap gap-3">
        <Button variant="primary" size="lg" onClick={close}>
          <ArrowRight size={20} strokeWidth={1.5} aria-hidden />
          {t('Empezar')}
        </Button>
      </div>
    </ModalDialog>
  );
}
