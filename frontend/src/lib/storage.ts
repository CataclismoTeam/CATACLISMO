// localStorage puede faltar o lanzar (modo privado, datos bloqueados): la app debe
// funcionar igual sin él, así que cada acceso va protegido.
export function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writeStored(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Sin almacenamiento: la preferencia dura solo esta sesión
  }
}
