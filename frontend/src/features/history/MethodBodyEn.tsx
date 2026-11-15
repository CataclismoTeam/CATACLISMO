// «Datos y métodos» en inglés. Mismo contenido que la versión española de MethodDialog.tsx:
// si cambia uno, hay que cambiar el otro.
import type { Manifest } from '../../data/types.ts';
import { formatCount } from '../../lib/format.ts';
import { SOURCES } from '../../lib/sources.ts';
import { HORIZON_H, NOW_H } from '../../map/scenario.ts';
import { SourceLink } from '../../ui/SourceLink.tsx';
import { decimal, sensorSpans } from './methodData.ts';
import { FactorTable, P, Section } from './methodParts.tsx';

const SOURCE_WHAT: [keyof typeof SOURCES, string][] = [
  ['firms', 'Fire Information for Resource Management System: satellite-detected hotspots.'],
  ['viirs', 'Sensor on the Suomi NPP, NOAA-20 and NOAA-21 satellites; ~375 m pixel.'],
  ['modis', 'Sensor on the Terra and Aqua satellites; ~1 km pixel, series since 2000.'],
  ['osm', 'Roads and populated places for the escape routes.'],
  ['maptiler', 'Basemap, terrain and contour lines.'],
];

const STEP: Record<string, string> = {
  'tipo excluido (volcán, fuente estática u offshore)':
    'excluded type (volcano, static source or offshore)',
  'NRT sobre fuente estática conocida': 'NRT over a known static source',
  'confianza baja': 'low confidence',
};

export default function MethodBodyEn({ manifest }: { manifest: Manifest }) {
  const { metodo, tiempo, filtros, registros } = manifest;
  const diag = metodo.diagnostico;
  return (
    <>
      <Section title="Sources">
        <ul className="m-0 list-disc pl-5">
          {SOURCE_WHAT.map(([key, what]) => (
            <li key={key}>
              <SourceLink source={SOURCES[key]} />: {what}
            </li>
          ))}
        </ul>
      </Section>

      <h2 className="m-0 mb-3 border-t border-line pt-4 text-lg font-semibold">
        History calendar (real)
      </h2>

      <Section title="Source">
        <P>
          NASA FIRMS / LANCE: MODIS Collection 6.1 (Terra and Aqua) and VIIRS S-NPP 375 m Collection
          2. Open data; NASA does not endorse this product.
        </P>
        <ul className="m-0 list-disc pl-5">
          <li>MODIS Collection 6.1, Terra and Aqua, 1 km (standard archive + NRT)</li>
          <li>VIIRS S-NPP Collection 2, 375 m (standard archive + NRT)</li>
        </ul>
        <P>
          Latest data: <strong>{tiempo.ultimoDato}</strong>. Series available since{' '}
          <strong>{tiempo.primerDato}</strong>; MODIS detections before {tiempo.anioInicial} are
          still to be downloaded.
        </P>
      </Section>

      <Section title="Which sensor feeds each period">
        <ul className="m-0 list-disc pl-5">
          {sensorSpans(manifest).map((span) => (
            <li key={span.from}>
              {span.from} – {span.to}: <strong>{span.sensors.replace('+', ' and ')}</strong>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Why harmonise">
        <P>
          VIIRS sees 375 m pixels and MODIS 1 km pixels: over the same fire VIIRS flags about{' '}
          {formatCount(1 / metodo.factorGlobal)} times more hotspots. Adding them up as they are
          would suggest more burning since VIIRS exists.
        </P>
      </Section>

      <Section title="Method">
        <P>
          Ratio of MODIS/VIIRS counts per calendar month. Using the {diag.mesesDeCalibracion}{' '}
          complete months in which both sensors worked at the same time, we compute, for each month
          of the year, how many MODIS detections there are per VIIRS detection (factor k). The
          result is expressed in MODIS-equivalent detections:
        </P>
        <ul className="m-0 list-disc pl-5">
          <li>MODIS only: counted as is.</li>
          <li>VIIRS only: VIIRS detections × k.</li>
          <li>Both: mean of MODIS and VIIRS × k.</li>
        </ul>
        <FactorTable manifest={manifest} />
        {diag.correlacionMensual !== null && diag.errorRelativoMediano !== null && (
          <P>
            Check: month by month, MODIS and VIIRS × k have a correlation of{' '}
            {decimal().format(diag.correlacionMensual)} and differ by a median{' '}
            {Math.round(diag.errorRelativoMediano * 100)} %.
          </P>
        )}
      </Section>

      <Section title="Which detections count">
        <P>
          Of {formatCount(registros.leidos)} downloaded detections, {formatCount(registros.usados)}{' '}
          are used. Only vegetation fires with nominal or high confidence count (MODIS ≥{' '}
          {filtros.confianzaMinimaModis}; VIIRS without the low class).
        </P>
        <ul className="m-0 list-disc pl-5">
          {registros.detalle.map((row) => (
            <li key={row.paso + row.sensor}>
              {formatCount(row.descartadas)} from {row.sensor}: {STEP[row.paso] ?? row.paso}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Calendar limitations">
        <ul className="m-0 list-disc pl-5">
          <li>
            The two sensors pass at different times and resolutions: a short or small fire may be
            seen by only one of them.
          </li>
          <li>The factor is an average for all of Spain; in a given area it may differ.</li>
          <li>Months marked with * use near-real-time data and change once consolidated.</li>
          <li>
            False positives remain (very hot surfaces, reflections), and fires under clouds or dense
            smoke go undetected.
          </li>
          <li>A detection is not a fire: a large fire produces many.</li>
        </ul>
      </Section>

      <h2 className="m-0 mt-6 mb-3 border-t border-line pt-4 text-lg font-semibold">
        Map: simulated spread
      </h2>

      <Section title="What it is">
        <P>
          A demonstration model, not an operational one. It shows what a prediction would look like
          at the command post; it does not replace a simulator such as FARSITE or Wildfire Analyst.
        </P>
      </Section>

      <Section title="How it is computed">
        <P>
          The fire spreads as an ellipse, faster downwind. For a wind of V km/h, the head advances
          at v = 0.6 + 0.045·V km/h and the ellipse stretches with e = min(0.85; 0.35 + V/60). In a
          direction at an angle θ to the spread:
        </P>
        <p className="m-0 text-center font-mono">v(θ) = v · (1 − e) / (1 − e · cos θ)</p>
        <P>
          Each 250 m cell stores its arrival time (distance / v(θ)), with a fixed ±25 % noise so the
          edge is not a perfect ellipse. What arrives in the first {NOW_H} h is the «active» fire;
          up to {HORIZON_H} h, the prediction in three bands (1–2, 2–4 and 4–6 h). Intensity and
          flame height are derived from that time: they are indicative, not physical.
        </P>
      </Section>

      <Section title="What it does not take into account">
        <ul className="m-0 list-disc pl-5">
          <li>Real fuel (vegetation type, load) or its moisture.</li>
          <li>Terrain slope: fire runs faster uphill.</li>
          <li>Wind changes, gusts or the effect of terrain on wind.</li>
          <li>Firebreaks, roads, rivers or suppression work.</li>
        </ul>
        <P>
          That is why uncertainty grows with time: the 4–6 h band is much less reliable than the 1–2
          h band.
        </P>
      </Section>

      <Section title="Escape routes">
        <P>
          The team&apos;s algorithm (backend/search): its own wind-driven spread and a space-time A*
          search on a 100 m grid with <SourceLink source={SOURCES.osm} /> roads. For each threatened
          place it looks for a route to a refuge that does not cross the fire; the margin is the
          spare time it computes against the fire.
        </P>
      </Section>

      <Section title="Illustrative halo of real fires">
        <P>
          FIRMS does not provide wind. The optional halo around active real fires uses a fixed
          example wind (westerly, 15 km/h): it is an illustration, not a forecast.
        </P>
      </Section>
    </>
  );
}
