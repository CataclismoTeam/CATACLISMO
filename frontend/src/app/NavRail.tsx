import { useT } from '../lib/i18n.ts';
import { Flame, Siren, Truck, type LucideIcon } from 'lucide-react';
import { cn } from '../lib/cn.ts';
import { useUi } from '../store/ui.ts';

interface Module {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Panel que abre y cierra el botón */
  panel: 'incendios' | 'unidades' | 'avisos';
}

// Registro de módulos: solo los que funcionan (nada de botones desactivados que parezcan humo)
const MODULES: Module[] = [
  { id: 'incendios', label: 'Incendios', icon: Flame, panel: 'incendios' },
  { id: 'unidades', label: 'Unidades', icon: Truck, panel: 'unidades' },
  { id: 'avisos', label: 'Avisos', icon: Siren, panel: 'avisos' },
];

export function NavRail() {
  const leftPanel = useUi((s) => s.leftPanel);
  const setLeftPanel = useUi((s) => s.setLeftPanel);
  const critical = useUi((s) => s.criticalAlerts);
  const t = useT();

  return (
    <nav
      aria-label={t('Módulos')}
      className="order-last flex shrink-0 gap-1 border-t border-line bg-surface p-1.5 pb-[max(0.375rem,env(safe-area-inset-bottom))] lg:order-first lg:w-21 lg:flex-col lg:border-t-0 lg:border-r lg:pb-1.5"
    >
      {MODULES.map(({ id, label, icon: Icon, panel }) => {
        const open = leftPanel === panel;
        return (
          <button
            key={id}
            type="button"
            aria-pressed={open}
            title={t(open ? 'Cerrar {x}' : 'Abrir {x}', { x: t(label).toLowerCase() })}
            onClick={() => setLeftPanel(open ? null : panel)}
            className={cn(
              'flex h-14 flex-1 cursor-pointer flex-col items-center justify-center gap-1 rounded-md border text-xs text-ink hover:bg-hover lg:flex-none',
              open ? 'border-line-strong bg-hover' : 'border-transparent',
            )}
          >
            <span className="relative">
              <Icon size={20} strokeWidth={1.5} aria-hidden />
              {panel === 'avisos' && critical > 0 && (
                <span className="absolute -top-1.5 -right-2.5 grid h-4 min-w-4 place-items-center rounded-full bg-fire px-1 font-mono text-[0.6875rem] leading-none font-bold text-canvas">
                  {critical}
                  <span className="sr-only"> {critical === 1 ? t('crítico') : t('críticos')}</span>
                </span>
              )}
            </span>
            {t(label)}
          </button>
        );
      })}
    </nav>
  );
}
