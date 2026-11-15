import { useT } from '../lib/i18n.ts';
import { Layers, Link, Ruler, Search } from 'lucide-react';
import { useUi } from '../store/ui.ts';
import { Button } from '../ui/Button.tsx';
import { copyLink } from './useShareHash.ts';

/**
 * Botones sobre el mapa, arriba a la derecha: buscar (solo en pantallas sin buscador en la barra),
 * regla, copiar enlace y capas. En móvil solo iconos, salvo «Capas».
 */
export function MapToolbar({
  showSearch,
  searchOpen,
  onSearch,
  onCopied,
}: {
  showSearch: boolean;
  searchOpen: boolean;
  onSearch: () => void;
  onCopied: (ok: boolean) => void;
}) {
  const measuring = useUi((s) => s.mapTool === 'medir');
  const setMapTool = useUi((s) => s.setMapTool);
  const layersOpen = useUi((s) => s.layersOpen);
  const setLayersOpen = useUi((s) => s.setLayersOpen);
  const t = useT();

  return (
    <div
      role="toolbar"
      aria-label={t('Herramientas del mapa')}
      className="flex gap-2 max-md:absolute max-md:top-3 max-md:right-14"
    >
      {showSearch && (
        <Button aria-pressed={searchOpen} onClick={onSearch} className="px-2.5">
          <Search size={16} strokeWidth={1.5} aria-hidden />
          <span className="max-md:sr-only">{t('Buscar')}</span>
        </Button>
      )}
      <Button
        aria-pressed={measuring}
        title={t('Medir distancias y superficies')}
        onClick={() => setMapTool(measuring ? null : 'medir')}
        className="px-2.5"
      >
        <Ruler size={16} strokeWidth={1.5} aria-hidden />
        <span className="max-md:sr-only">{t('Medir')}</span>
      </Button>
      <Button
        title={t('Copiar un enlace a esta vista')}
        onClick={() => void copyLink().then(onCopied)}
        className="px-2.5"
      >
        <Link size={16} strokeWidth={1.5} aria-hidden />
        <span className="max-md:sr-only">{t('Copiar enlace')}</span>
      </Button>
      <Button
        aria-pressed={layersOpen}
        data-abre="capas"
        onClick={() => setLayersOpen(!layersOpen)}
      >
        <Layers size={16} strokeWidth={1.5} aria-hidden />
        {t('Capas')}
      </Button>
    </div>
  );
}
