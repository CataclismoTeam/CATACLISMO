import { describe, expect, it } from 'vitest';
import { areaKm2, formatArea, formatLength, lengthKm, type LonLat } from './measure.ts';

describe('regla del mapa', () => {
  it('un grado de latitud mide unos 111 km', () => {
    expect(
      lengthKm([
        [0, 40],
        [0, 41],
      ]),
    ).toBeCloseTo(111.2, 0);
  });

  it('suma los tramos y, cerrada, el de vuelta', () => {
    const square: LonLat[] = [
      [0, 0],
      [0.01, 0],
      [0.01, 0.01],
      [0, 0.01],
    ];
    const side = lengthKm(square.slice(0, 2));
    expect(lengthKm(square)).toBeCloseTo(3 * side, 6);
    expect(lengthKm(square, true)).toBeCloseTo(4 * side, 6);
  });

  it('el área de un cuadrado de 0,01° en el ecuador es de unos 1,24 km²', () => {
    const square: LonLat[] = [
      [0, 0],
      [0.01, 0],
      [0.01, 0.01],
      [0, 0.01],
    ];
    expect(areaKm2(square)).toBeCloseTo(1.236, 2);
    // El sentido de los vértices no cambia el área
    expect(areaKm2([...square].reverse())).toBeCloseTo(areaKm2(square), 9);
  });

  it('menos de tres puntos no tienen área', () => {
    expect(
      areaKm2([
        [0, 0],
        [1, 1],
      ]),
    ).toBe(0);
  });

  it('formatea metros, km, hectáreas y km²', () => {
    expect(formatLength(0.85)).toBe('850 m');
    expect(formatLength(3.254)).toBe('3,25 km');
    expect(formatLength(42.04)).toBe('42 km');
    expect(formatArea(0.42)).toBe('42 ha');
    expect(formatArea(12.34)).toBe('12,3 km²');
  });
});
