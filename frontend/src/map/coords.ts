// Coordenadas escritas a mano en el buscador.
/** «36.49, -5.2», «36.49 -5.2» o «36,49; -5,2»: latitud y longitud en grados decimales. */
export function parseCoords(text: string): [lon: number, lat: number] | null {
  const t = text.trim();
  // Con punto y coma la coma puede ser decimal; si no, la coma separa latitud y longitud
  const parts = t.includes(';')
    ? t.split(';').map((p) => p.trim().replace(',', '.'))
    : t.split(/[\s,]+/).filter(Boolean);
  if (parts.length !== 2) return null;
  const [lat, lon] = parts.map(Number);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return [lon, lat];
}
