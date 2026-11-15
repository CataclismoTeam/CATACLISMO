// Idioma de la interfaz: español (por defecto) o inglés, para un jurado internacional.
// El texto en español es la clave: t('Capas') devuelve «Capas» en español y «Layers» en inglés.
// El diccionario inglés (lib/en.ts) solo se descarga si se elige inglés.
import { create } from 'zustand';
import { initialView } from './hash.ts';
import { readStored, writeStored } from './storage.ts';

export type Lang = 'es' | 'en';
type Dict = Record<string, string>;

const KEY = 'cataclismo.idioma';

interface LangState {
  lang: Lang;
  /** Diccionario inglés, cuando ya se ha descargado */
  dict: Dict | null;
  setLang: (lang: Lang) => Promise<void>;
}

async function loadDict(): Promise<Dict> {
  return (await import('./en.ts')).default;
}

function applyDocument(lang: Lang) {
  if (typeof document !== 'undefined') document.documentElement.lang = lang;
}

export const useLang = create<LangState>((set) => ({
  lang: 'es',
  dict: null,
  setLang: async (lang) => {
    writeStored(KEY, lang);
    if (lang === 'en') {
      const dict = await loadDict();
      set({ lang, dict });
    } else {
      set({ lang });
    }
    applyDocument(lang);
  },
}));

// Un enlace compartido con &l=en manda sobre lo guardado
const wanted: Lang = initialView.lang ?? (readStored<Lang>(KEY, 'es') === 'en' ? 'en' : 'es');
if (wanted === 'en') void useLang.getState().setLang('en');

/** Traduce un texto en español. {nombre} se sustituye por vars.nombre. */
export function t(es: string, vars?: Record<string, string | number>): string {
  const { lang, dict } = useLang.getState();
  const text = (lang === 'en' && dict?.[es]) || es;
  return vars ? text.replace(/\{(\w+)\}/g, (m, k: string) => String(vars[k] ?? m)) : text;
}

/** t() que vuelve a pintar el componente al cambiar de idioma. */
export function useT(): typeof t {
  useLang((s) => s.lang);
  useLang((s) => s.dict);
  return t;
}

export const isEnglish = () => useLang.getState().lang === 'en';

/** true en inglés: para bloques de texto con enlaces o negritas que se escriben por idioma. */
export const useEnglish = () => useLang((s) => s.lang === 'en');

/** Locale para números y fechas: «1.234,5» en español, «1,234.5» en inglés. */
export const locale = () => (isEnglish() ? 'en-GB' : 'es-ES');
