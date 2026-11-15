// Tras un despliegue, los chunks con hash antiguo desaparecen de GitHub Pages: una pestaña
// abierta antes falla al cargar un panel diferido (lazy). La solución es recargar la página
// para traer el index.html nuevo, una sola vez por minuto para no entrar en bucle.

const KEY = 'cataclismo:recarga-por-chunk';
const WINDOW_MS = 60_000;

/** ¿Es un fallo al descargar un módulo dinámico (chunk viejo o red)? */
export function isChunkLoadError(error: unknown): boolean {
  const msg = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|ChunkLoadError|Unable to preload CSS/i.test(
    msg,
  );
}

/** Recarga la página si no se ha recargado por esto hace poco. Devuelve si recarga. */
export function reloadForStaleChunk(): boolean {
  let last = 0;
  try {
    last = Number(sessionStorage.getItem(KEY) ?? 0);
  } catch {
    // Sin sessionStorage: se recarga igualmente
  }
  if (Date.now() - last < WINDOW_MS) return false;
  try {
    sessionStorage.setItem(KEY, String(Date.now()));
  } catch {
    // Ignorado
  }
  window.location.reload();
  return true;
}

/** Engancha el evento de Vite que avisa de un chunk que no se pudo cargar. */
export function installStaleChunkReload() {
  window.addEventListener('vite:preloadError', (event) => {
    if (reloadForStaleChunk()) event.preventDefault();
  });
}
