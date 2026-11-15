import { describe, expect, it } from 'vitest';
import { formatHash, parseHash } from './hash.ts';

describe('estado compartible en el hash', () => {
  it('lee y escribe la vista completa', () => {
    const hash = '#sim=bermeja&inc=INC-001&z=11.5&c=-5.20000,36.49000&m=3d';
    const view = parseHash(hash);
    expect(view).toEqual({
      sim: 'bermeja',
      inc: 'INC-001',
      zoom: 11.5,
      center: [-5.2, 36.49],
      mode: '3d',
    });
    expect(formatHash(view)).toBe(hash);
  });

  it('ignora valores fuera de rango o con formato raro', () => {
    expect(parseHash('#z=99&c=500,10&m=4d&sim=<script>')).toEqual({});
    expect(parseHash('')).toEqual({});
  });

  it('una vista vacía no deja hash', () => {
    expect(formatHash({})).toBe('');
  });
});
