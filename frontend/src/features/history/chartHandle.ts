// El gráfico del mes vive en un chunk aparte (ECharts); aquí deja su imagen para el PNG.
let getImage: (() => string) | undefined;

export function registerChart(fn: (() => string) | undefined): void {
  getImage = fn;
}

export function chartImage(): string | undefined {
  return getImage?.();
}
