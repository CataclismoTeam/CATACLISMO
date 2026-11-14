// Proveedores cartográficos intercambiables. Con clave de MapTiler (VITE_MAPTILER_KEY) se usan
// sus estilos, su relieve y sus curvas de nivel; sin clave, fuentes abiertas sin token.
// Para trabajar sin Internet bastaría con otro proveedor que apunte a teselas locales (PMTiles).
import type { RasterDEMSourceSpecification, StyleSpecification } from 'maplibre-gl';
import type { Basemap } from '../store/ui.ts';

const KEY: string | undefined = import.meta.env.VITE_MAPTILER_KEY || undefined;
const MT = 'https://api.maptiler.com';

export interface Provider {
  id: 'maptiler' | 'abierto';
  label: string;
  style: (basemap: Basemap) => string | StyleSpecification;
  dem: RasterDEMSourceSpecification;
  /** Teselas vectoriales de curvas de nivel (capa "contour", campo "height" en metros) */
  contours?: string;
  attribution: string;
}

const maptiler = (key: string): Provider => ({
  id: 'maptiler',
  label: 'MapTiler',
  style: (basemap) =>
    `${MT}/maps/${{ satelite: 'hybrid', topografico: 'topo-v2', oscuro: 'dataviz-dark' }[basemap]}/style.json?key=${key}`,
  dem: {
    type: 'raster-dem',
    url: `${MT}/tiles/terrain-rgb-v2/tiles.json?key=${key}`,
    tileSize: 256,
    encoding: 'mapbox',
  },
  contours: `${MT}/tiles/contours-v2/tiles.json?key=${key}`,
  attribution: 'MapTiler · OpenStreetMap',
});

function rasterStyle(tiles: string[], attribution: string, maxzoom = 19): StyleSpecification {
  return {
    version: 8,
    sources: { base: { type: 'raster', tiles, tileSize: 256, maxzoom, attribution } },
    layers: [{ id: 'base', type: 'raster', source: 'base' }],
  };
}

const open: Provider = {
  id: 'abierto',
  label: 'fuentes abiertas',
  style: (basemap) =>
    basemap === 'satelite'
      ? rasterStyle(
          [
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          ],
          'Esri, Maxar, Earthstar Geographics',
        )
      : basemap === 'topografico'
        ? rasterStyle(
            ['https://tile.opentopomap.org/{z}/{x}/{y}.png'],
            '© OpenTopoMap (CC-BY-SA) · © OpenStreetMap',
            17,
          )
        : rasterStyle(
            ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'],
            '© CARTO · © OpenStreetMap',
          ),
  dem: {
    type: 'raster-dem',
    tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
    tileSize: 256,
    maxzoom: 15,
    encoding: 'terrarium',
    attribution: 'Mapzen Terrain Tiles',
  },
  attribution: 'Esri · OpenTopoMap · CARTO · OpenStreetMap',
};

export const provider: Provider = KEY ? maptiler(KEY) : open;
