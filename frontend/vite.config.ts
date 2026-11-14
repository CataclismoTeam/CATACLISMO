import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Ruta base en GitHub Pages: https://cataclismoteam.github.io/CATACLISMO/
const BASE = '/CATACLISMO/';

export default defineConfig({
  base: BASE,
  // La clave de MapTiler se lee de .env en la raíz del repo (ignorado por git)
  envDir: '..',
  plugins: [react(), tailwindcss()],
  build: {
    // El build va a dist/ en la raíz del repo (lo recogen el CI y GitHub Pages)
    outDir: '../dist',
    emptyOutDir: true,
  },
});
