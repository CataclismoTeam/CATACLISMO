# Relevo: estado de CATACLISMO (2026-11-14, tarde)

Reglas del usuario: español, pnpm siempre, nada de push ni PR sin permiso, `main` protegida (PR + squash + Conventional Commits). La especificación original está en `docs/PROMPT-FRONTEND.md`; donde choque, manda este documento.

## Hecho (rama `feat/shell-calendario`, sale de `feat/datos-hotspots`; todo local, sin push)

| Commit    | Bloque                                                                                                                                                                                                                                                                                                                                                                          |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `93548db` | Armonización MODIS + VIIRS (`tools/build-hotspots`, Python + uv) y agregados en `frontend/public/data/`                                                                                                                                                                                                                                                                         |
| `1e94bb7` | Shell oscuro, tokens, calendario mes × año con mediana, anomalía, CSV, PNG y metodología                                                                                                                                                                                                                                                                                        |
| `4baec53` | Mapa MapLibre + MapTiler: 2D/3D (2.5D = 3D inclinado + exageración), satélite / topográfico con curvas / oscuro, sombreado, detecciones FIRMS reales como cuadrados del píxel, escenarios simulados forestal e interfaz urbano-forestal con fuego en celdas de 250 m y predicción con trama, vías de escape, iconos de unidades con estado, panel de capas, coordenadas y radio |
| `cf0b267` | Predicción más legible y marcadores separados                                                                                                                                                                                                                                                                                                                                   |

Comprobado en local: format, tsc, oxlint, Vitest (16), build, `check:size`, `check:links`, `check:html`, guardián y e2e (22 en verde, escritorio y móvil).

Clave de MapTiler: `VITE_MAPTILER_KEY` en `.env` de la raíz (ignorado; `vite.config.ts` usa `envDir: '..'`). En el CI llega como `vars.VITE_MAPTILER_KEY` al paso Build de `deploy.yml` (ya creada). Sin clave, el mapa usa Esri, OpenTopoMap, CARTO y Terrarium de AWS.

## Avisos

- Los e2e arrancan el mapa en 2D (`localStorage cataclismo.mapa`), porque sin GPU el relieve 3D satura el navegador. El test de modos solo comprueba el cambio de estado.
- Las capturas de regresión visual se borraron en `1e94bb7` y el CI las regenerará (ver `tests/visual/README.md`). Revisa el artefacto `referencias-visuales` y súbelas.
- Lighthouse no se ha pasado en local con el mapa siempre cargado. Revísalo en el CI (rendimiento ≥ 0,9).
- `tools/serve.mjs` sirve ahora `.mjs` como JavaScript (lo necesita el worker de MapLibre 6).

## Pendiente

1. Push de las ramas y PRs a `main` (pedir permiso).
2. Conectar el área del calendario con el mapa: dibujar un rectángulo en el mapa y usarlo como área del calendario.
3. Pulsar un mes del calendario para filtrar las detecciones del mapa a ese periodo (hoy el mapa muestra los últimos 90 días).
4. Ficha al pulsar una celda de fuego o una detección (fecha, sensor, FRP, confianza).
5. `docs/ux-ruta-de-lanzamiento.md` (7 puntos GO / AÚN NO con evidencia) y actualizar `frontend/README.md` a MapLibre.
6. Diseño offline (no implementado): proveedor de teselas locales con PMTiles en `src/map/providers.ts`.
