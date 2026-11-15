import { describe, expect, it } from 'vitest';
import { alertedOperators, backendDetails, bboxOf, type JuliCollection } from './backend.ts';

describe('backend: utilidades del mapa', () => {
  it('bboxOf recorre puntos, líneas y polígonos', () => {
    expect(
      bboxOf([
        {
          type: 'Feature',
          properties: {},
          geometry: { type: 'Point', coordinates: [-6, 41, 500] },
        },
        {
          type: 'Feature',
          properties: {},
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [-7, 40],
                [-5, 40],
                [-5, 42],
                [-7, 40],
              ],
            ],
          },
        },
      ]),
    ).toEqual([-7, 40, -5, 42]);
    expect(bboxOf([])).toBeUndefined();
  });

  it('alertedOperators lee las alertas de prueba de vida', () => {
    const juli: JuliCollection = {
      type: 'FeatureCollection',
      features: [],
      metadata: { proof_of_life: { alerts: [{ operator_id: 'op_1' }, { operator_id: 'op_2' }] } },
    };
    expect([...alertedOperators(juli)]).toEqual(['op_1', 'op_2']);
    expect(alertedOperators(undefined).size).toBe(0);
  });

  it('la ficha de un operario con alerta lo dice', () => {
    const { title, rows } = backendDetails({
      feature_type: 'field_operator',
      callsign: 'ALFA-1',
      name: 'Ana',
      status: 'en_ruta',
      alerta: true,
    });
    expect(title).toBe('ALFA-1 · Ana');
    expect(rows).toContainEqual(['Estado', 'En ruta']);
    expect(rows).toContainEqual(['Prueba de vida', 'Sin respuesta']);
  });

  it('la ficha de una ruta da distancia y tiempo', () => {
    const { rows } = backendDetails({
      feature_type: 'evacuation_route',
      distance_km: 17.314,
      estimated_time_minutes: 232.6,
      max_fire_probability_on_route: 0.12,
    });
    expect(rows.find(([l]) => l === 'Distancia')?.[1]).toMatch(/^17[.,]3 km$/);
    expect(rows.find(([l]) => l === 'Tiempo estimado')?.[1]).toBe('233 min');
  });
});
