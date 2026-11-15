import { describe, expect, it } from 'vitest';
import { alertLevel, alertsFor, minutes, routeBbox } from './alerts.ts';
import type { Route } from './scenario.ts';

const route = (nombre: string, llegadaFuegoMin: number, margenMin: number | null): Route => ({
  nombre,
  desde: nombre,
  refugio: 'Refugio',
  coords: [
    [-5, 36],
    [-4.9, 36.2],
  ],
  distanciaKm: 10,
  tiempoMin: 20,
  margenMin,
  llegadaFuegoMin,
});

describe('avisos de núcleos en riesgo', () => {
  it('clasifica por el margen: crítico < 30, alto < 90 y vigilancia el resto', () => {
    expect(alertLevel(0)).toBe('critico');
    expect(alertLevel(29)).toBe('critico');
    expect(alertLevel(30)).toBe('alto');
    expect(alertLevel(89)).toBe('alto');
    expect(alertLevel(90)).toBe('vigilancia');
  });

  it('sin margen calculado es crítico', () => {
    expect(alertLevel(null)).toBe('critico');
  });

  it('ordena por la llegada del fuego', () => {
    const list = alertsFor([route('C', 300, 200), route('A', 30, 5), route('B', 100, 60)]);
    expect(list.map((a) => a.route.nombre)).toEqual(['A', 'B', 'C']);
    expect(list.map((a) => a.level)).toEqual(['critico', 'alto', 'vigilancia']);
  });

  it('escribe los minutos en horas cuando pasan de 60', () => {
    expect(minutes(45)).toBe('45 min');
    expect(minutes(60)).toBe('1 h');
    expect(minutes(257)).toBe('4 h 17 min');
  });

  it('calcula el rectángulo de la ruta', () => {
    expect(routeBbox(route('A', 1, 1))).toEqual([-5, 36, -4.9, 36.2]);
  });
});
