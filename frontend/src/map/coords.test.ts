import { describe, expect, it } from 'vitest';
import { parseCoords } from './coords.ts';

describe('coordenadas del buscador', () => {
  it('lee «lat, lon», «lat lon» y «lat; lon» con coma decimal', () => {
    expect(parseCoords('36.49, -5.2')).toEqual([-5.2, 36.49]);
    expect(parseCoords(' 36.49   -5.2 ')).toEqual([-5.2, 36.49]);
    expect(parseCoords('36,49; -5,2')).toEqual([-5.2, 36.49]);
  });

  it('rechaza texto y valores fuera de rango', () => {
    expect(parseCoords('Ronda')).toBeNull();
    expect(parseCoords('95, 10')).toBeNull();
    expect(parseCoords('36.4')).toBeNull();
  });
});
