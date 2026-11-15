import type { Manifest } from '../../data/types.ts';
import { formatCount, MONTHS_SHORT } from '../../lib/format.ts';
import { useHistory } from '../../store/history.ts';
import { useUi } from '../../store/ui.ts';
import { SourceLink } from '../../app/Provenance.tsx';
import { SOURCES } from '../../lib/sources.ts';
import { Dialog } from '../../ui/Dialog.tsx';
import { HORIZON_H, NOW_H } from '../../map/scenario.ts';
import { monthInfo } from './series.ts';

const decimal = new Intl.NumberFormat('es-ES', {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});

/** Tramos consecutivos de la serie según el sensor que los alimenta. */
function sensorSpans(manifest: Manifest): { from: string; to: string; sensors: string }[] {
  const spans: { from: string; to: string; sensors: string }[] = [];
  const label = (mi: number) =>
    `${MONTHS_SHORT[mi % 12]} ${manifest.tiempo.anioInicial + Math.floor(mi / 12)}`;
  for (let mi = 0; mi < manifest.tiempo.meses; mi++) {
    const { sensors } = monthInfo(manifest, mi);
    if (!sensors) continue;
    const last = spans.at(-1);
    if (last?.sensors === sensors) last.to = label(mi);
    else spans.push({ from: label(mi), to: label(mi), sensors });
  }
  return spans;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5 last:mb-0">
      <h3 className="m-0 mb-1.5 text-base font-semibold">{title}</h3>
      <div className="flex flex-col gap-2 text-sm">{children}</div>
    </section>
  );
}

const P = ({ children }: { children: React.ReactNode }) => <p className="m-0">{children}</p>;

export default function MethodDialog() {
  const open = useUi((s) => s.methodOpen);
  const setOpen = useUi((s) => s.setMethodOpen);
  const manifest = useHistory((s) => s.manifest);
  if (!manifest) return null;
  const { metodo, tiempo, filtros, registros } = manifest;
  const diag = metodo.diagnostico;

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title="Datos y métodos"
      description="De dónde salen los datos, cómo se calculan el calendario y el mapa, y qué límites tienen."
      className="w-[min(94vw,48rem)]"
    >
      <Section title="Fuentes">
        <ul className="m-0 list-disc pl-5">
          {[SOURCES.firms, SOURCES.viirs, SOURCES.modis, SOURCES.osm, SOURCES.maptiler].map((s) => (
            <li key={s.url}>
              <SourceLink source={s} />: {s.what}
            </li>
          ))}
        </ul>
      </Section>

      <h2 className="m-0 mb-3 border-t border-line pt-4 text-lg font-semibold">
        Calendario histórico (real)
      </h2>

      <Section title="Fuente">
        <P>{manifest.fuente}</P>
        <ul className="m-0 list-disc pl-5">
          <li>{manifest.productos.MODIS}</li>
          <li>{manifest.productos.VIIRS}</li>
        </ul>
        <P>
          Último dato: <strong>{tiempo.ultimoDato}</strong>. Serie disponible desde{' '}
          <strong>{tiempo.primerDato}</strong>; las detecciones de MODIS anteriores a{' '}
          {tiempo.anioInicial} están pendientes de descarga.
        </P>
      </Section>

      <Section title="Qué sensor alimenta cada tramo">
        <ul className="m-0 list-disc pl-5">
          {sensorSpans(manifest).map((span) => (
            <li key={span.from}>
              {span.from} – {span.to}: <strong>{span.sensors.replace('+', ' y ')}</strong>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Por qué hay que armonizar">
        <P>
          VIIRS ve píxeles de 375 m y MODIS de 1 km: sobre el mismo incendio VIIRS marca unas{' '}
          {formatCount(1 / metodo.factorGlobal)} veces más puntos calientes. Sumarlos tal cual haría
          creer que arde más desde que existe VIIRS.
        </P>
      </Section>

      <Section title="Método">
        <P>
          {metodo.nombre}. Con los {diag.mesesDeCalibracion} meses completos en que ambos sensores
          funcionaron a la vez se calcula, para cada mes del año, cuántas detecciones de MODIS hay
          por cada una de VIIRS (factor k). El resultado se expresa en {metodo.unidad}:
        </P>
        <ul className="m-0 list-disc pl-5">
          <li>Solo MODIS: se cuenta tal cual.</li>
          <li>Solo VIIRS: detecciones VIIRS × k.</li>
          <li>Ambos: media de MODIS y de VIIRS × k.</li>
        </ul>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-right text-[0.8125rem] tabular-nums">
            <caption className="mb-1 text-left text-ink-muted">
              Factor k por mes del año e intervalo del 95 %
            </caption>
            <thead>
              <tr className="text-ink-muted">
                <th scope="row" className="text-left font-medium">
                  Mes
                </th>
                {MONTHS_SHORT.map((m) => (
                  <th key={m} scope="col" className="px-1 font-medium">
                    {m}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row" className="text-left font-medium">
                  k
                </th>
                {metodo.factores.map((k, i) => (
                  <td key={i} className="px-1">
                    {decimal.format(k)}
                  </td>
                ))}
              </tr>
              <tr className="text-ink-muted">
                <th scope="row" className="text-left font-medium">
                  Mín.
                </th>
                {metodo.intervalo95.map(([lo], i) => (
                  <td key={i} className="px-1">
                    {decimal.format(lo)}
                  </td>
                ))}
              </tr>
              <tr className="text-ink-muted">
                <th scope="row" className="text-left font-medium">
                  Máx.
                </th>
                {metodo.intervalo95.map(([, hi], i) => (
                  <td key={i} className="px-1">
                    {decimal.format(hi)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
        {diag.correlacionMensual !== null && diag.errorRelativoMediano !== null && (
          <P>
            Comprobación: mes a mes, MODIS y VIIRS × k tienen una correlación de{' '}
            {decimal.format(diag.correlacionMensual)} y difieren un{' '}
            {Math.round(diag.errorRelativoMediano * 100)} % de mediana.
          </P>
        )}
      </Section>

      <Section title="Qué detecciones se cuentan">
        <P>
          De {formatCount(registros.leidos)} detecciones descargadas se usan{' '}
          {formatCount(registros.usados)}. Solo cuentan los fuegos de vegetación, con confianza
          nominal o alta (MODIS ≥ {filtros.confianzaMinimaModis}; VIIRS sin la clase baja).
        </P>
        <ul className="m-0 list-disc pl-5">
          {registros.detalle.map((row) => (
            <li key={row.paso + row.sensor}>
              {formatCount(row.descartadas)} de {row.sensor}: {row.paso}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Limitaciones del calendario">
        <ul className="m-0 list-disc pl-5">
          <li>
            Los dos sensores pasan a horas distintas y con distinta resolución: un fuego corto o
            pequeño puede verlo solo uno.
          </li>
          <li>El factor es una media de toda España; en una zona concreta puede ser otro.</li>
          <li>
            Los meses marcados con * usan datos en casi tiempo real y cambian al consolidarse.
          </li>
          <li>
            Quedan falsos positivos (superficies muy calientes, reflejos) y fuegos sin detectar bajo
            nubes o humo denso.
          </li>
          <li>Una detección no es un incendio: un incendio grande genera muchas.</li>
        </ul>
      </Section>

      <h2 className="m-0 mt-6 mb-3 border-t border-line pt-4 text-lg font-semibold">
        Mapa: propagación simulada
      </h2>

      <Section title="Qué es">
        <P>
          Un modelo de demostración, no operativo. Sirve para enseñar cómo se vería una predicción
          en el puesto de mando; no sustituye a un simulador como FARSITE o Wildfire Analyst.
        </P>
      </Section>

      <Section title="Cómo se calcula">
        <P>
          El fuego avanza en elipse, más rápido a favor del viento. Para un viento de V km/h, la
          cabeza avanza a v = 0,6 + 0,045·V km/h y la elipse se alarga con e = mín(0,85; 0,35 +
          V/60). En una dirección que forma un ángulo θ con el avance:
        </P>
        <p className="m-0 text-center font-mono">v(θ) = v · (1 − e) / (1 − e · cos θ)</p>
        <P>
          Cada celda de 250 m guarda su hora de llegada (distancia / v(θ)), con un ruido fijo de ±25
          % para que el borde no sea una elipse perfecta. Lo que llega en la primera {NOW_H} h es el
          incendio «activo»; hasta {HORIZON_H} h, la predicción en tres franjas (1–2, 2–4 y 4–6 h).
          La intensidad y la altura de llama se derivan de esa hora: son orientativas, no físicas.
        </P>
      </Section>

      <Section title="Qué no tiene en cuenta">
        <ul className="m-0 list-disc pl-5">
          <li>El combustible real (tipo de vegetación, carga) ni su humedad.</li>
          <li>La pendiente del terreno: el fuego sube más rápido ladera arriba.</li>
          <li>Cambios de viento, rachas ni el efecto del relieve sobre el viento.</li>
          <li>Cortafuegos, carreteras, ríos ni las labores de extinción.</li>
        </ul>
        <P>
          Por eso la incertidumbre crece con el tiempo: la franja de 4–6 h es mucho menos fiable que
          la de 1–2 h.
        </P>
      </Section>

      <Section title="Vías de escape">
        <P>
          Algoritmo del equipo (backend/search): su propia propagación con viento y una búsqueda A*
          espacio-temporal sobre una rejilla de 100 m con las carreteras de{' '}
          <SourceLink source={SOURCES.osm} />. Para cada núcleo amenazado busca la ruta a un refugio
          que no cruza el fuego; el margen es el tiempo de sobra que calcula frente al fuego.
        </P>
      </Section>

      <Section title="Halo ilustrativo de los incendios reales">
        <P>
          FIRMS no da el viento. El halo opcional alrededor de los incendios reales activos usa un
          viento fijo de ejemplo (poniente, 15 km/h): es una ilustración, no un pronóstico.
        </P>
      </Section>
    </Dialog>
  );
}
