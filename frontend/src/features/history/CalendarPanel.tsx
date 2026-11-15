import { useT } from '../../lib/i18n.ts';
import { Download, FileImage, Info } from 'lucide-react';
import { lazy, Suspense, useCallback, useState } from 'react';
import { ErrorBoundary } from '../../app/ErrorBoundary.tsx';
import { useHistory } from '../../store/history.ts';
import { useUi } from '../../store/ui.ts';
import { Button } from '../../ui/Button.tsx';
import { AnomalyCard } from './AnomalyCard.tsx';
import { AreaForm } from './AreaForm.tsx';
import { calendarPng, pngFileName } from './calendarPng.ts';
import { buildCsv, csvFileName, download } from './csv.ts';
import { Heatmap } from './Heatmap.tsx';
import type { CalendarModel } from './model.ts';

const MonthChart = lazy(() => import('./MonthChart.tsx'));

function Exports({ model }: { model: CalendarModel }) {
  const area = useHistory((s) => s.area);
  const gridReady = useHistory((s) => s.gridStatus === 'listo');
  const setMethodOpen = useUi((s) => s.setMethodOpen);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const t = useT();

  const savePng = async () => {
    setBusy(true);
    setError('');
    try {
      download(pngFileName(area, model.yearRange), await calendarPng(model, area));
    } catch {
      setError(t('No se pudo crear la imagen. Vuelve a intentarlo.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={!gridReady}
          title={gridReady ? undefined : t('Disponible cuando terminen de cargar los datos')}
          onClick={() =>
            download(
              csvFileName(area, model.yearRange),
              buildCsv(model.series, model.manifest, area, model.yearRange),
            )
          }
        >
          <Download size={16} strokeWidth={1.5} aria-hidden />
          {t('Descargar CSV')}
        </Button>
        <Button disabled={busy} onClick={() => void savePng()}>
          <FileImage size={16} strokeWidth={1.5} aria-hidden />
          {busy ? t('Creando imagen…') : t('Descargar PNG')}
        </Button>
        <Button variant="ghost" onClick={() => setMethodOpen(true)}>
          <Info size={16} strokeWidth={1.5} aria-hidden />
          {t('Cómo se armonizan los datos')}
        </Button>
      </div>
      {error && (
        <p role="alert" className="m-0 text-sm text-fire">
          {error}
        </p>
      )}
    </div>
  );
}

export default function CalendarPanel({ model }: { model: CalendarModel }) {
  const select = useHistory((s) => s.select);
  // Pulsar un mes también lo pinta en el mapa (capa «Actividad del mes del calendario»)
  const selectAndShow = useCallback(
    (mi: number) => {
      select(mi);
      useUi.getState().setLayer('mes', true);
    },
    [select],
  );
  const empty = model.total === 0;
  const t = useT();

  return (
    <div className="grid gap-x-6 gap-y-5 p-4 xl:grid-cols-[15rem_minmax(0,1fr)_22rem]">
      <AreaForm />

      {empty ? (
        <p className="m-0 self-center text-center text-base xl:col-span-2">
          {t('Sin detecciones en esta área entre {a} y {b}. Amplía el radio o elige otra zona.', {
            a: model.yearRange[0],
            b: model.yearRange[1],
          })}
        </p>
      ) : (
        <>
          <Heatmap model={model} onSelect={selectAndShow} />
          <div className="flex min-w-0 flex-col gap-4">
            <AnomalyCard model={model} onSelect={select} />
            <ErrorBoundary what={t('el gráfico')}>
              <Suspense fallback={<div role="status" className="h-44 rounded-md bg-raised" />}>
                <MonthChart model={model} />
              </Suspense>
              <p className="m-0 text-xs text-ink-muted">
                {t(
                  'Línea discontinua: mediana. Banda gris: lo habitual (percentiles 25 a 75). Barra hueca: mes incompleto.',
                )}
              </p>
            </ErrorBoundary>
            <Exports model={model} />
          </div>
        </>
      )}
    </div>
  );
}
