// Tipos del manifiesto que genera tools/build-hotspots (hotspots-manifest-v1.json).
export interface GridSpec {
  oeste: number;
  sur: number;
  este: number;
  norte: number;
  celdaGrados: number;
  columnas: number;
  filas: number;
  celdasConDatos: number;
}

export interface DiscardRow {
  paso: string;
  sensor: string;
  descartadas: number;
}

export interface YearFile {
  anio: number;
  entradas: number;
  fichero: string;
  bytes: number;
  sha256: string;
}

export interface Manifest {
  version: number;
  generado: string;
  fuente: string;
  productos: { MODIS: string; VIIRS: string };
  rejilla: GridSpec;
  tiempo: {
    anioInicial: number;
    meses: number;
    primerDato: string;
    ultimoDato: string;
    sensores: Partial<Record<'MODIS' | 'VIIRS', { desde: string; hasta: string }>>;
    diasDelMes: number[];
    diasCubiertos: { MODIS: number[]; VIIRS: number[] };
    provisional: number[];
    usadoParaCalibrar: number[];
  };
  metodo: {
    nombre: string;
    unidad: string;
    regla: string;
    factores: number[];
    factorGlobal: number;
    intervalo95: [number, number][];
    ambitoDelFactor: string[];
    diagnostico: {
      mesesDeCalibracion: number;
      correlacionMensual: number | null;
      errorRelativoMediano: number | null;
      razonPorAnio: Record<string, number>;
    };
    semilla: number;
  };
  filtros: {
    tipos: number[];
    confianzaMinimaModis: number;
    descartaViirsBaja: boolean;
    mascaraEstaticaNrt: { minimo: number; grados: number };
  };
  registros: { leidos: number; descartados: number; usados: number; detalle: DiscardRow[] };
  totalesMensuales: { modis: number[]; viirs: number[]; armonizado: number[] };
  recientes: { fichero: string; desde: string; hasta: string };
  celdas: string;
  anios: YearFile[];
}

/** Conteos mensuales de un año, en estructura de arrays (ver tools/build-hotspots/README.md). */
export interface YearChunk {
  year: number;
  n: number;
  h: Float32Array;
  frpM: Float32Array;
  frpV: Float32Array;
  cell: Uint16Array;
  m: Uint16Array;
  v: Uint16Array;
  month: Uint8Array;
}

export interface GridData {
  /** Identificador global (fila * columnas + columna) de cada celda con datos */
  cells: Uint32Array;
  years: YearChunk[];
}
