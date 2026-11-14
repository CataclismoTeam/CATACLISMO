# Relevo: estado de CATACLISMO (2026-11-14, noche) · front v2

Reglas del usuario: español, pnpm siempre. **Todo se sube directamente a `main`** (sin ramas
ni PR), integrando antes `origin/main` y pasando las comprobaciones locales. Nunca `--force`.

## Hecho (en `main`, etiqueta `front-v2.0.0`)

- **Datos** (`tools/build-hotspots`): armonización MODIS + VIIRS, calendario mes × año,
  incendios reales de los últimos 90 días por comunidad autónoma (`incidents-v1.json`) y vías
  de escape de las simulaciones con el algoritmo del equipo (`escape-routes-v1.json`).
- **Mapa** (MapLibre + MapTiler): 2D y 3D (el 2.5D es el 3D inclinado), satélite y
  topográfico con curvas. Incendios reales como superficie de calor con contorno; de lejos,
  un icono por incendio. 12 simulaciones en 9 comunidades, con propagación prevista.
- **Operativo**: unidades por aire, tierra (en grupos) y mar; radio con General Tierra y un
  canal por grupo; fichas en el lateral, se cierran con Esc.
- **Interfaz**: Ajustes con tema sistema/claro/oscuro, daltonismo (Okabe-Ito) y modo
  proyección; favicon propio. Lighthouse local: rendimiento 0,93; resto 1.

Clave de MapTiler: `VITE_MAPTILER_KEY` en `.env` (ignorado). En el CI, `vars.VITE_MAPTILER_KEY`.

## Avisos

- Los e2e arrancan el mapa en 2D (sin GPU el 3D satura el navegador).
- El mapa se carga al cerrar el briefing en la primera visita (rendimiento).
- Las capturas de regresión visual las genera el CI (artefacto `referencias-visuales`):
  revisarlas y subirlas a `tests/visual/__screenshots__/`.
- Montes de Toledo no tiene vías de escape: no hay núcleos amenazados en el área.

## Pendiente

1. Dibujar el área del calendario en el mapa y filtrar el mapa por el mes elegido.
2. Ficha al pulsar una detección suelta (fecha, sensor, FRP, confianza).
3. `docs/ux-ruta-de-lanzamiento.md` (7 puntos GO / AÚN NO) y `frontend/README.md` a MapLibre.
4. Exponer en FastAPI el modelo CATA y las vías de escape cuando haya pesos entrenados.
5. Modo sin conexión: teselas locales (PMTiles) en `src/map/providers.ts`.
