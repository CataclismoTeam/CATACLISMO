import { describe, expect, it } from 'vitest';
import { defaultApiBase, normalizeBase, validBase, wsUrl } from './api.ts';

describe('URL del backend', () => {
  it('quita espacios y barras finales', () => {
    expect(normalizeBase(' http://localhost:8000/ ')).toBe('http://localhost:8000');
    expect(normalizeBase('https://api.ejemplo.es//')).toBe('https://api.ejemplo.es');
  });

  it('solo acepta http y https', () => {
    expect(validBase('http://localhost:8000')).toBe(true);
    expect(validBase('https://api.ejemplo.es')).toBe(true);
    expect(validBase('javascript:alert(1)')).toBe(false);
    expect(validBase('ftp://x')).toBe(false);
    expect(validBase('localhost:8000')).toBe(false);
    expect(validBase('')).toBe(false);
  });

  it('la URL del build solo se usa fuera de localhost', () => {
    const prod = 'https://cataclismo-api.onrender.com/';
    expect(defaultApiBase('cataclismoteam.github.io', prod)).toBe(
      'https://cataclismo-api.onrender.com',
    );
    expect(defaultApiBase('localhost', prod)).toBe('');
    expect(defaultApiBase('127.0.0.1', prod)).toBe('');
    expect(defaultApiBase('cataclismoteam.github.io', undefined)).toBe('');
  });

  it('el WebSocket usa el mismo host con ws o wss', () => {
    expect(wsUrl('http://localhost:8000')).toBe('ws://localhost:8000/ws');
    expect(wsUrl('https://api.ejemplo.es')).toBe('wss://api.ejemplo.es/ws');
  });
});
