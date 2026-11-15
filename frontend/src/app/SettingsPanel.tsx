import { useLang, useT } from '../lib/i18n.ts';
import { Monitor, Moon, Sun, X, type LucideIcon } from 'lucide-react';
import { cn } from '../lib/cn.ts';
import { useUi, type Cvd, type Theme } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';

const THEMES: [Theme, string, LucideIcon][] = [
  ['sistema', 'Sistema', Monitor],
  ['claro', 'Claro', Sun],
  ['oscuro', 'Oscuro', Moon],
];

const CVD: [Cvd, string, string][] = [
  ['ninguno', 'Desactivado', 'Colores habituales.'],
  ['protanopia', 'Protanopía', 'Dificultad con el rojo: estados en azul, naranja y rosa.'],
  ['deuteranopia', 'Deuteranopía', 'Dificultad con el verde: estados en azul, naranja y rosa.'],
  ['tritanopia', 'Tritanopía', 'Dificultad con azul y amarillo: estados en verde, rojo y rosa.'],
];

function Option({
  checked,
  onClick,
  children,
}: {
  checked: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      onClick={onClick}
      className={cn(
        'flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-left text-sm pointer-coarse:min-h-11',
        checked ? 'border-accent bg-hover font-semibold' : 'border-line hover:bg-hover',
      )}
    >
      {children}
    </button>
  );
}

/** Ajustes de la interfaz: tema, accesibilidad (daltonismo) y modo proyección. */
export function SettingsPanel() {
  const open = useUi((s) => s.settingsOpen);
  const setOpen = useUi((s) => s.setSettingsOpen);
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const cvd = useUi((s) => s.cvd);
  const setCvd = useUi((s) => s.setCvd);
  const projection = useUi((s) => s.projection);
  const toggleProjection = useUi((s) => s.toggleProjection);
  const t = useT();
  const lang = useLang((s) => s.lang);
  const setLang = useLang((s) => s.setLang);
  if (!open) return null;

  return (
    <aside
      aria-label={t('Ajustes')}
      className="absolute top-14 right-2 z-(--z-overlay) w-[min(24rem,calc(100vw-1rem))] rounded-lg border border-line-strong bg-surface shadow-panel"
    >
      <header className="flex items-center justify-between border-b border-line px-4 py-2">
        <h2 className="m-0 text-base font-semibold">{t('Ajustes')}</h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t('Cerrar ajustes')}
          onClick={() => setOpen(false)}
        >
          <X size={20} strokeWidth={1.5} aria-hidden />
        </Button>
      </header>

      <section className="border-b border-line px-4 py-3">
        <h3 className="m-0 mb-2 text-xs font-semibold tracking-wide text-ink-muted uppercase">
          {t('Idioma')} · Language
        </h3>
        <div role="radiogroup" aria-label={t('Idioma')} className="grid grid-cols-2 gap-2">
          <Option checked={lang === 'es'} onClick={() => void setLang('es')}>
            <span lang="es">Español</span>
          </Option>
          <Option checked={lang === 'en'} onClick={() => void setLang('en')}>
            <span lang="en">English</span>
          </Option>
        </div>
      </section>

      <section className="border-b border-line px-4 py-3">
        <h3 className="m-0 mb-2 text-xs font-semibold tracking-wide text-ink-muted uppercase">
          {t('Tema')}
        </h3>
        <div role="radiogroup" aria-label={t('Tema')} className="grid grid-cols-3 gap-2">
          {THEMES.map(([id, label, Icon]) => (
            <Option key={id} checked={theme === id} onClick={() => setTheme(id)}>
              <Icon size={16} strokeWidth={1.5} aria-hidden />
              {t(label)}
            </Option>
          ))}
        </div>
      </section>

      <section className="border-b border-line px-4 py-3">
        <h3 className="m-0 mb-1 text-xs font-semibold tracking-wide text-ink-muted uppercase">
          {t('Accesibilidad')}
        </h3>
        <p className="m-0 mb-2 text-sm">{t('Daltonismo')}</p>
        <div role="radiogroup" aria-label={t('Daltonismo')} className="flex flex-col gap-1.5">
          {CVD.map(([id, label, hint]) => (
            <Option key={id} checked={cvd === id} onClick={() => setCvd(id)}>
              <span className="flex flex-col">
                {t(label)}
                <span className="text-xs font-normal text-ink-muted">{t(hint)}</span>
              </span>
            </Option>
          ))}
        </div>
      </section>

      <section className="px-4 py-3">
        <h3 className="m-0 mb-2 text-xs font-semibold tracking-wide text-ink-muted uppercase">
          {t('Pantalla')}
        </h3>
        <label className="flex cursor-pointer items-center justify-between gap-3 text-sm pointer-coarse:min-h-11">
          <span>
            {t('Modo proyección')}
            <span className="block text-xs text-ink-muted">
              {t('Texto más grande para leer a distancia')}
            </span>
          </span>
          <input
            name="modo-proyeccion"
            type="checkbox"
            role="switch"
            checked={projection}
            onChange={toggleProjection}
            className="size-5 accent-accent"
          />
        </label>
      </section>
    </aside>
  );
}
