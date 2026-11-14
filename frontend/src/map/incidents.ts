// Incendios detectados (REALES) por toda España: los genera tools/build-hotspots agrupando
// las detecciones FIRMS de los últimos 90 días y asignando comunidad autónoma y provincia.
import type { FeatureCollection, MultiPolygon, Point, Polygon } from 'geojson';

export interface Incident {
  id: string;
  comunidad: string;
  provincia: string;
  lon: number;
  lat: number;
  bbox: [number, number, number, number];
  desde: string;
  hasta: string;
  /** Con detecciones en los últimos días del dato (no significa "sin extinguir") */
  activo: boolean;
  detecciones: number;
  sensores: string[];
  frpMax: number;
  frpTotal: number;
  areaKm2: number;
  contorno: Polygon | MultiPolygon;
}

export interface IncidentsFile {
  desde: string;
  hasta: string;
  comunidades: string[];
  incendios: Incident[];
}

export type IncidentProps = Pick<
  Incident,
  'id' | 'comunidad' | 'provincia' | 'activo' | 'frpTotal' | 'detecciones'
>;

export async function loadIncidents(): Promise<IncidentsFile> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/incidents-v1.json`);
  if (!response.ok) throw new Error('incendios no disponibles');
  return (await response.json()) as IncidentsFile;
}

const props = (i: Incident): IncidentProps => ({
  id: i.id,
  comunidad: i.comunidad,
  provincia: i.provincia,
  activo: i.activo,
  frpTotal: i.frpTotal,
  detecciones: i.detecciones,
});

export function outlines(
  file: IncidentsFile,
): FeatureCollection<Polygon | MultiPolygon, IncidentProps> {
  return {
    type: 'FeatureCollection',
    features: file.incendios.map((i) => ({
      type: 'Feature',
      properties: props(i),
      geometry: i.contorno,
    })),
  };
}

export function incidentPoints(file: IncidentsFile): FeatureCollection<Point, IncidentProps> {
  return {
    type: 'FeatureCollection',
    features: file.incendios.map((i) => ({
      type: 'Feature',
      properties: props(i),
      geometry: { type: 'Point', coordinates: [i.lon, i.lat] },
    })),
  };
}

/** Incendios agrupados por comunidad autónoma, con los activos primero. */
export function byRegion(file: IncidentsFile): [string, Incident[]][] {
  const groups = new Map<string, Incident[]>();
  for (const i of file.incendios) groups.set(i.comunidad, [...(groups.get(i.comunidad) ?? []), i]);
  return [...groups.entries()]
    .map(([name, list]): [string, Incident[]] => [
      name,
      list.sort((a, b) => Number(b.activo) - Number(a.activo) || b.frpTotal - a.frpTotal),
    ])
    .sort((a, b) => a[0].localeCompare(b[0], 'es'));
}
