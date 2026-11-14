// Origen de datos de la app. Hoy solo existe LocalSource (ficheros estáticos del build);
// cuando haya backend, una implementación sobre FastAPI/WebSocket la sustituye sin tocar la UI.
import type { GridData, Manifest, YearChunk } from './types.ts';

export interface DataSource {
  readonly label: string;
  manifest(): Promise<Manifest>;
  grid(manifest: Manifest): Promise<GridData>;
}

export class DataError extends Error {}

/** Interpreta un binario anual: Float32 ×3, Uint16 ×3 y Uint8, todos de longitud n. */
export function parseYearChunk(buffer: ArrayBuffer, year: number, n: number): YearChunk {
  if (buffer.byteLength !== n * 19) {
    throw new DataError(`El fichero de ${year} no tiene el tamaño esperado.`);
  }
  return {
    year,
    n,
    h: new Float32Array(buffer, 0, n),
    frpM: new Float32Array(buffer, 4 * n, n),
    frpV: new Float32Array(buffer, 8 * n, n),
    cell: new Uint16Array(buffer, 12 * n, n),
    m: new Uint16Array(buffer, 14 * n, n),
    v: new Uint16Array(buffer, 16 * n, n),
    month: new Uint8Array(buffer, 18 * n, n),
  };
}

export class LocalSource implements DataSource {
  readonly label = 'Demo · sin conexión a backend';
  private readonly base: string;
  private manifestPromise?: Promise<Manifest>;
  private gridPromise?: Promise<GridData>;

  constructor(base = `${import.meta.env.BASE_URL}data/`) {
    this.base = base;
  }

  private async fetch(file: string): Promise<Response> {
    let response: Response;
    try {
      response = await fetch(this.base + file);
    } catch {
      throw new DataError('No hay conexión para descargar los datos.');
    }
    if (!response.ok) throw new DataError(`No se encontró el fichero de datos ${file}.`);
    return response;
  }

  manifest(): Promise<Manifest> {
    this.manifestPromise ??= this.fetch('hotspots-manifest-v1.json')
      .then((r) => r.json() as Promise<Manifest>)
      .catch((error: unknown) => {
        this.manifestPromise = undefined; // permite reintentar
        throw error;
      });
    return this.manifestPromise;
  }

  grid(manifest: Manifest): Promise<GridData> {
    this.gridPromise ??= Promise.all([
      this.fetch(manifest.celdas).then((r) => r.arrayBuffer()),
      ...manifest.anios.map((y) => this.fetch(y.fichero).then((r) => r.arrayBuffer())),
    ])
      .then(([cells, ...years]) => ({
        cells: new Uint32Array(cells),
        years: years.map((buffer, i) =>
          parseYearChunk(buffer, manifest.anios[i].anio, manifest.anios[i].entradas),
        ),
      }))
      .catch((error: unknown) => {
        this.gridPromise = undefined;
        throw error;
      });
    return this.gridPromise;
  }
}

export const dataSource: DataSource = new LocalSource();
