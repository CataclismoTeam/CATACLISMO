import { describe, expect, it } from 'vitest';
import { type Detections, fireCells } from './detections.ts';

const det = (lon: number, fecha: string): Detections['geojson']['features'][number] => ({
  type: 'Feature',
  properties: { sensor: 'VIIRS', frp: 10, fecha, confianza: 'nominal', provisional: false },
  geometry: { type: 'Point', coordinates: [lon, 40] },
});

const detections = (features: Detections['geojson']['features']): Detections => ({
  from: '2026-08-05',
  to: '2026-11-02',
  geojson: { type: 'FeatureCollection', features },
});

describe('fireCells', () => {
  it('marca activa la celda con fuego en los últimos días del dato y ceniza la antigua', () => {
    const cells = fireCells(
      detections([det(-3, '2026-11-01 12:00 UTC'), det(-2, '2026-10-20 12:00 UTC')]),
    );
    const byLon = (lon: number) =>
      cells.features.filter((f) => Math.abs(f.geometry.coordinates[0][0][0] - lon) < 0.01);
    expect(byLon(-3).every((f) => f.properties.activo)).toBe(true);
    expect(byLon(-2).every((f) => !f.properties.activo)).toBe(true);
  });

  it('una celda con una detección reciente sigue activa aunque tenga otras antiguas', () => {
    const cells = fireCells(
      detections([det(-3, '2026-10-01 12:00 UTC'), det(-3, '2026-11-02 08:00 UTC')]),
    );
    expect(cells.features.every((f) => f.properties.activo)).toBe(true);
  });
});
