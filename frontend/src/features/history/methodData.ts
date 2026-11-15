// Datos derivados del manifiesto para la metodología (comunes a los dos idiomas).
import type { Manifest } from '../../data/types.ts';
import { monthsShort, numberFormat } from '../../lib/format.ts';
import { monthInfo } from './series.ts';

/** Tres decimales en el idioma actual (factores k). */
export const decimal = () => numberFormat({ minimumFractionDigits: 3, maximumFractionDigits: 3 });

/** Tramos consecutivos de la serie según el sensor que los alimenta. */
export function sensorSpans(manifest: Manifest): { from: string; to: string; sensors: string }[] {
  const spans: { from: string; to: string; sensors: string }[] = [];
  const label = (mi: number) =>
    `${monthsShort()[mi % 12]} ${manifest.tiempo.anioInicial + Math.floor(mi / 12)}`;
  for (let mi = 0; mi < manifest.tiempo.meses; mi++) {
    const { sensors } = monthInfo(manifest, mi);
    if (!sensors) continue;
    const last = spans.at(-1);
    if (last?.sensors === sensors) last.to = label(mi);
    else spans.push({ from: label(mi), to: label(mi), sensors });
  }
  return spans;
}
