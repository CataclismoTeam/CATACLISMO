// Botones de la barra superior. Van en el bundle inicial; sus paneles se cargan al abrirlos.
import { Radio, Settings } from 'lucide-react';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';

export function RadioButton() {
  const open = useUi((s) => s.radioOpen);
  const setOpen = useUi((s) => s.setRadioOpen);
  return (
    <Button
      variant={open ? 'secondary' : 'ghost'}
      aria-pressed={open}
      aria-label="Radio"
      title="Radio: canales del operativo"
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
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-pressed={open}
      aria-label="Ajustes"
      title="Ajustes: tema, accesibilidad y pantalla"
      onClick={() => {
        setRadioOpen(false);
        setOpen(!open);
      }}
    >
      <Settings size={20} strokeWidth={1.5} aria-hidden />
    </Button>
  );
}
