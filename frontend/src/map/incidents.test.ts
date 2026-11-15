import { describe, expect, it } from 'vitest';
import { incidentAt, type Incident } from './incidents.ts';

const fire = (id: string, lon: number, lat: number, half = 0.02): Incident =>
  ({ id, lon, lat, bbox: [lon - half, lat - half, lon + half, lat + half] }) as Incident;

describe('incidentAt', () => {
  const fires = [fire('A', -5, 40), fire('B', -5.1, 40)];

  it('devuelve el incendio cuyo encuadre contiene el punto', () => {
    expect(incidentAt(fires, [-5.01, 40.01])?.id).toBe('A');
  });

  it('acepta uno cercano aunque el punto quede fuera de su encuadre', () => {
    expect(incidentAt(fires, [-5, 40.025], 3)?.id).toBe('A');
  });

  it('entre dos, gana el más cercano', () => {
    expect(incidentAt(fires, [-5.07, 40])?.id).toBe('B');
  });

  it('lejos de todos no devuelve nada', () => {
    expect(incidentAt(fires, [-3, 38])).toBeUndefined();
  });
});
