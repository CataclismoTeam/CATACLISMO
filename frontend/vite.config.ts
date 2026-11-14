import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy';

// Ruta base en GitHub Pages: https://cataclismoteam.github.io/CATACLISMO/
const BASE = '/CATACLISMO/';
const CESIUM_BUILD = 'node_modules/cesium/Build/Cesium';

export default defineConfig({
  base: BASE,
  plugins: [
    react(),
    tailwindcss(),
    // Cesium carga en tiempo de ejecución sus workers, assets y widgets desde CESIUM_BASE_URL
    viteStaticCopy({
      targets: [
        {
          src: `${CESIUM_BUILD}/{Workers,ThirdParty,Assets,Widgets}/**/*`,
          dest: 'cesium',
          // Quita node_modules/cesium/Build/Cesium del destino: dist/cesium/Workers/...
          rename: { stripBase: 4 },
        },
      ],
    }),
  ],
  define: {
    CESIUM_BASE_URL: JSON.stringify(`${BASE}cesium/`),
  },
  build: {
    // El build va a dist/ en la raíz del repo (lo recogen el CI y GitHub Pages)
    outDir: '../dist',
    emptyOutDir: true,
  },
});
