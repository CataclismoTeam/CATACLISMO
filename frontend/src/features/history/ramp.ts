// Rampa secuencial cividis: perceptualmente uniforme y legible con cualquier daltonismo
// y en escala de grises (su luminosidad crece de forma monótona).
const STOPS = [
  [0, 34, 78],
  [18, 53, 112],
  [59, 73, 108],
  [87, 93, 109],
  [112, 113, 115],
  [138, 134, 120],
  [165, 156, 116],
  [195, 179, 105],
  [225, 204, 85],
  [254, 232, 56],
] as const;

export interface RampColor {
  background: string;
  /** Color de texto con contraste suficiente sobre ese fondo */
  text: string;
}

/** t en [0, 1] */
export function rampColor(t: number): RampColor {
  const clamped = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0));
  const pos = clamped * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(pos));
  const f = pos - i;
  const [r, g, b] = STOPS[i].map((c, k) => Math.round(c + (STOPS[i + 1][k] - c) * f));
  const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  return { background: `rgb(${r} ${g} ${b})`, text: luminance > 0.48 ? '#0b0f14' : '#f4f6f9' };
}

/**
 * Escala de raíz cuadrada: la actividad de fuego es muy asimétrica (unos pocos meses
 * concentran casi todo) y una escala lineal dejaría el resto del calendario plano.
 */
export function scale(value: number, max: number): number {
  return max > 0 ? Math.sqrt(Math.max(0, value) / max) : 0;
}

export function rampGradient(steps = 10): string {
  const colors = Array.from({ length: steps + 1 }, (_, i) => rampColor(i / steps).background);
  return `linear-gradient(to right, ${colors.join(', ')})`;
}
