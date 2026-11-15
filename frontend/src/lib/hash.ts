// Estado compartible en el hash de la URL: #sim=bermeja&inc=INC-001&z=11.5&c=-5.2,36.49&m=3d
// Se lee una vez al cargar (store y cámara inicial) y el mapa lo reescribe al cambiar.
export interface SharedView {
  sim?: string;
  inc?: string;
  zoom?: number;
  center?: [lon: number, lat: number];
  mode?: '2d' | '3d';
}

export function parseHash(hash: string): SharedView {
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const view: SharedView = {};
  const sim = params.get('sim');
  if (sim && /^[\w-]{1,40}$/.test(sim)) view.sim = sim;
  const inc = params.get('inc');
  if (inc && /^[\w-]{1,20}$/.test(inc)) view.inc = inc;
  const zoom = Number(params.get('z'));
  if (params.has('z') && zoom >= 0 && zoom <= 22) view.zoom = zoom;
  const [lon, lat] = (params.get('c') ?? '').split(',').map(Number);
  if (Math.abs(lon) <= 180 && Math.abs(lat) <= 90 && params.get('c')?.includes(',')) {
    view.center = [lon, lat];
  }
  const mode = params.get('m');
  if (mode === '2d' || mode === '3d') view.mode = mode;
  return view;
}

export function formatHash(view: SharedView): string {
  const parts: string[] = [];
  if (view.sim) parts.push(`sim=${view.sim}`);
  if (view.inc) parts.push(`inc=${view.inc}`);
  if (view.zoom !== undefined) parts.push(`z=${Math.round(view.zoom * 100) / 100}`);
  if (view.center) parts.push(`c=${view.center[0].toFixed(5)},${view.center[1].toFixed(5)}`);
  if (view.mode) parts.push(`m=${view.mode}`);
  return parts.length ? `#${parts.join('&')}` : '';
}

/** Vista compartida con la que se abrió la página. */
export const initialView: SharedView =
  typeof window === 'undefined' ? {} : parseHash(window.location.hash);
