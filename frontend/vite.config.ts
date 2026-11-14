import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { defineConfig } from 'vite';

// Ruta base en GitHub Pages: https://cataclismoteam.github.io/CATACLISMO/
const BASE = '/CATACLISMO/';
// Versión del front (2.x = "versión 2 del front"), visible en el briefing
const { version } = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf8'),
) as {
  version: string;
};

export default defineConfig({
  base: BASE,
  // La clave de MapTiler se lee de .env en la raíz del repo (ignorado por git)
  envDir: '..',
  plugins: [react(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  build: {
    // El build va a dist/ en la raíz del repo (lo recogen el CI y GitHub Pages)
    outDir: '../dist',
    emptyOutDir: true,
  },
});
