import { describe, expect, it } from 'vitest';
import { parseYearChunk } from '../../data/source.ts';
import type { GridSpec, Manifest } from '../../data/types.ts';
import { areaCells, cellCenter, contains, haversineKm, type Area } from './area.ts';
import { buildCsv, csvFileName } from './csv.ts';
import { rampColor, scale } from './ramp.ts';
import { aggregate, lastCompleteMonth, lastMonthWithData, monthInfo } from './series.ts';
import { anomaly, quantile, reference } from './stats.ts';

const grid: GridSpec = {
  oeste: -10,
  sur: 35,
  este: -9,
  norte: 36,
  celdaGrados: 0.5,
  columnas: 2,
  filas: 2,
  celdasConDatos: 2,
};

// Dos años; el último mes solo tiene 10 de 31 días y es provisional
const manifest = {
  version: 1,
  generado: '2026-11-14T00:00:00+00:00',
  rejilla: grid,
  tiempo: {
    anioInicial: 2020,
    meses: 24,
    diasDelMes: Array.from({ length: 24 }, () => 30),
    diasCubiertos: {
      MODIS: Array.from({ length: 24 }, (_, i) => (i === 23 ? 0 : i === 22 ? 10 : 30)),
      VIIRS: Array.from({ length: 24 }, (_, i) => (i === 23 ? 0 : i === 22 ? 10 : 30)),
    },
    provisional: Array.from({ length: 24 }, (_, i) => (i === 22 ? 3 : 0)),
  },
  metodo: { nombre: 'Razón, "con comillas"', factores: Array.from({ length: 12 }, () => 0.3) },
} as unknown as Manifest;

function chunk(
  year: number,
  rows: [cell: number, month: number, m: number, v: number, h: number][],
) {
  const n = rows.length;
  const buffer = new ArrayBuffer(n * 19);
  new Float32Array(buffer, 0, n).set(rows.map((r) => r[4]));
  new Uint16Array(buffer, 12 * n, n).set(rows.map((r) => r[0]));
  new Uint16Array(buffer, 14 * n, n).set(rows.map((r) => r[2]));
  new Uint16Array(buffer, 16 * n, n).set(rows.map((r) => r[3]));
  new Uint8Array(buffer, 18 * n, n).set(rows.map((r) => r[1]));
  return parseYearChunk(buffer, year, n);
}

const data = {
  cells: Uint32Array.from([0, 3]), // esquina suroeste y esquina noreste
  years: [
    chunk(2020, [
      [0, 0, 2, 6, 1.9],
      [1, 0, 1, 3, 0.95],
      [1, 7, 10, 30, 9.5],
    ]),
    chunk(2021, [[0, 7, 4, 12, 3.8]]),
  ],
};

describe('área', () => {
  it('mide distancias sobre la esfera', () => {
    expect(haversineKm(36.5, -5, 37.5, -5)).toBeCloseTo(111.2, 0);
  });

  it('sitúa el centro de cada celda', () => {
    expect(cellCenter(0, grid)).toEqual({ lat: 35.25, lon: -9.75 });
    expect(cellCenter(3, grid)).toEqual({ lat: 35.75, lon: -9.25 });
  });

  it('decide qué puntos caen dentro de cada tipo de área', () => {
    const square: Area = {
      kind: 'polygon',
      name: 'cuadro',
      ring: [
        [-10, 35],
        [-9.5, 35],
        [-9.5, 35.5],
        [-10, 35.5],
      ],
    };
    expect(contains(square, 35.25, -9.75)).toBe(true);
    expect(contains(square, 35.75, -9.25)).toBe(false);
    const circle: Area = { kind: 'circle', name: 'c', lat: 35.25, lon: -9.75, radiusKm: 10 };
    expect(contains(circle, 35.25, -9.75)).toBe(true);
    expect(contains(circle, 35.75, -9.25)).toBe(false);
  });

  it('cuenta celdas y superficie del área', () => {
    const all = areaCells({ kind: 'all', name: 'todo' }, grid, data.cells);
    expect(all.gridCells).toBe(4);
    expect(all.dataCells).toBe(2);
    const south: Area = { kind: 'bbox', name: 'sur', west: -10, south: 35, east: -9, north: 35.5 };
    const part = areaCells(south, grid, data.cells);
    expect([...part.mask]).toEqual([1, 0]);
    expect(part.gridCells).toBe(2);
    expect(part.km2).toBeGreaterThan(4000);
    expect(part.km2).toBeLessThan(5500);
  });
});

describe('serie mensual', () => {
  it('suma todas las celdas cuando no hay máscara', () => {
    const s = aggregate(data, null, manifest);
    expect(s.m[0]).toBe(3);
    expect(s.v[0]).toBe(9);
    expect(s.h[0]).toBeCloseTo(2.85, 5);
    expect(s.m[7]).toBe(10);
    expect(s.m[19]).toBe(4);
    expect(s.m.reduce((a, b) => a + b, 0)).toBe(17);
  });

  it('suma solo las celdas del área', () => {
    const s = aggregate(data, Uint8Array.from([1, 0]), manifest);
    expect(s.m[0]).toBe(2);
    expect(s.m[7]).toBe(0);
    expect(s.m[19]).toBe(4);
  });

  it('distingue meses completos, parciales, provisionales y sin datos', () => {
    expect(monthInfo(manifest, 0)).toMatchObject({ state: 'completo', provisional: false });
    expect(monthInfo(manifest, 22)).toMatchObject({
      state: 'parcial',
      daysCovered: 10,
      provisional: true,
      sensors: 'MODIS+VIIRS',
    });
    expect(monthInfo(manifest, 23).state).toBe('sin datos');
    expect(lastMonthWithData(manifest)).toBe(22);
    expect(lastCompleteMonth(manifest)).toBe(21);
  });
});

describe('referencia y anomalía', () => {
  it('interpola cuantiles', () => {
    expect(quantile([1, 2, 3, 4], 0.5)).toBe(2.5);
    expect(quantile([5], 0.9)).toBe(5);
    expect(quantile([], 0.5)).toBeNaN();
  });

  // Diez años del mismo mes: 10, 20, …, 100
  const values = Array.from({ length: 120 }, (_, i) =>
    i % 12 === 7 ? (Math.floor(i / 12) + 1) * 10 : 0,
  );
  const complete = (mi: number) => mi !== 7 + 12 * 8;

  it('usa el mismo mes de los otros años, sin el propio ni los incompletos', () => {
    const ref = reference(values, 7 + 12 * 9, 2010, complete, [2010, 2019]);
    expect(ref.years).toEqual([2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017]);
    expect(ref.median).toBe(45);
    expect(reference(values, 7 + 12 * 9, 2010, complete, [2014, 2019]).years).toEqual([
      2014, 2015, 2016, 2017,
    ]);
  });

  it('clasifica por percentiles y da la diferencia con la mediana', () => {
    const ref = reference(values, 7 + 12 * 9, 2010, complete, [2010, 2019]);
    expect(anomaly(100, ref)).toMatchObject({ level: 'muy por encima', difference: 55 });
    expect(anomaly(70, ref).level).toBe('por encima');
    expect(anomaly(45, ref)).toMatchObject({ level: 'normal', ratio: 0 });
    expect(anomaly(10, ref).level).toBe('por debajo');
  });

  it('no clasifica con pocos años ni divide entre una mediana cero', () => {
    const few = reference(values, 7 + 12 * 9, 2010, complete, [2015, 2019]);
    expect(anomaly(100, few).level).toBe('sin referencia');
    const zeros = reference(values, 12 * 9, 2010, complete, [2010, 2019]);
    expect(anomaly(3, zeros).ratio).toBeNaN();
    expect(anomaly(3, zeros).level).toBe('muy por encima');
  });
});

describe('CSV', () => {
  const s = aggregate(data, null, manifest);
  const csv = buildCsv(s, manifest, { kind: 'all', name: 'España' }, [2020, 2021]);
  const lines = csv.slice(1).trimEnd().split('\r\n');

  it('lleva BOM, CRLF y una fila por mes con datos', () => {
    expect(csv.charCodeAt(0)).toBe(0xfeff);
    expect(lines).toHaveLength(1 + 23);
    expect(lines[0].split(',')).toContain('conteo_armonizado');
  });

  it('escapa comillas y comas y usa punto decimal', () => {
    expect(lines[1]).toContain('2020-01-01,2020,1,MODIS+VIIRS,3,9,2.85,0.3');
    expect(lines[1]).toContain('"Razón, ""con comillas"""');
    expect(lines[23]).toContain(',10,30,si,');
  });

  it('respeta el rango de años y nombra el fichero', () => {
    const one = buildCsv(s, manifest, { kind: 'all', name: 'España' }, [2021, 2021]);
    expect(one.trimEnd().split('\r\n')).toHaveLength(1 + 11);
    expect(csvFileName({ kind: 'all', name: 'Sierra Bermeja (Málaga)' }, [2012, 2026])).toBe(
      'cataclismo-fuego_sierra-bermeja-malaga_2012-2026.csv',
    );
  });
});

describe('rampa de color', () => {
  it('crece en luminosidad y cambia el color del texto', () => {
    expect(rampColor(0)).toEqual({ background: 'rgb(0 34 78)', text: '#f4f6f9' });
    expect(rampColor(1)).toEqual({ background: 'rgb(254 232 56)', text: '#0b0f14' });
    expect(rampColor(Number.NaN).background).toBe('rgb(0 34 78)');
  });

  it('escala con raíz cuadrada', () => {
    expect(scale(25, 100)).toBe(0.5);
    expect(scale(5, 0)).toBe(0);
  });
});
