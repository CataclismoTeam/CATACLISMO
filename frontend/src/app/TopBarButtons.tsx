// Botones de la barra superior. Van en el bundle inicial; sus paneles se cargan al abrirlos.
import { useLang, useT } from '../lib/i18n.ts';
import { Languages, Radio, Settings } from 'lucide-react';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';

/** ES ⇄ EN. En la barra desde 640 px (solo icono hasta 1024 px); en móvil, dentro de Ajustes. */
export function LanguageButton({ className }: { className?: string }) {
  const lang = useLang((s) => s.lang);
  const setLang = useLang((s) => s.setLang);
  const next = lang === 'es' ? 'en' : 'es';
  return (
    <Button
      variant="ghost"
      lang={next}
      aria-label={next === 'en' ? 'Switch to English' : 'Cambiar a español'}
      title={next === 'en' ? 'Switch to English' : 'Cambiar a español'}
      onClick={() => void setLang(next)}
      className={cn('px-2 font-mono', className)}
    >
      <Languages size={18} strokeWidth={1.5} aria-hidden />
      <span className="max-lg:sr-only" aria-hidden>
        {next.toUpperCase()}
      </span>
    </Button>
  );
}

export function RadioButton() {
  const open = useUi((s) => s.radioOpen);
  const setOpen = useUi((s) => s.setRadioOpen);
  const t = useT();
  return (
    <Button
      variant={open ? 'secondary' : 'ghost'}
      aria-pressed={open}
      aria-label="Radio"
      title={t('Radio: canales del operativo')}
      onClick={() => {
        useUi.getState().setSettingsOpen(false);
        setOpen(!open);
      }}
      className="px-2.5"
    >
      <Radio size={20} strokeWidth={1.5} aria-hidden />
      <span className="hidden xl:inline">Radio</span>
    </Button>
  );
}

export function SettingsButton() {
  const open = useUi((s) => s.settingsOpen);
  const setOpen = useUi((s) => s.setSettingsOpen);
  const setRadioOpen = useUi((s) => s.setRadioOpen);
  const t = useT();
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-pressed={open}
      aria-label={t('Ajustes')}
      title={t('Ajustes: tema, accesibilidad y pantalla')}
      onClick={() => {
        setRadioOpen(false);
        setOpen(!open);
      }}
    >
      <Settings size={20} strokeWidth={1.5} aria-hidden />
    </Button>
  );
}
