# Relevo: estado de CATACLISMO y lo que queda (2026-11-14)

Lee primero `docs/PROMPT-FRONTEND.md` (especificación). **Este documento prevalece sobre él** donde choquen.
Reglas del usuario: español, pnpm siempre, nada de push/PR sin pedir permiso, `main` protegida (todo por PR, squash, Conventional Commits).

## 1. Estado actual

### Rama `feat/datos-hotspots` (commit `93548db`, local, SIN push)

- `tools/build-hotspots/` (Python + uv): lee FIRMS de `data/raw/` (ignorado), empalma archivo + NRT, filtra (type=0, MODIS conf ≥ 30, VIIRS sin `l`, máscara de fuentes estáticas para NRT), calibra VIIRS→MODIS con una razón por mes del año (k≈0,30, correlación 0,982) y publica en `frontend/public/data/` (manifiesto + binarios por año, 1,4 MB). 10 pruebas de pytest en verde, ruff limpio. README con el método.
- Regenerar: `uv run --project tools/build-hotspots build-hotspots --in data/raw --out frontend/public/data --interim data/interim`
- `deploy.yml`: paso nuevo en el job backend (ruff + pytest de build-hotspots). `.gitignore`: `data/raw/`, `data/interim/`, `DL_FIRE_*/`.

### Rama `feat/shell-calendario` (sale de la anterior; SIN commit, todo en el árbol de trabajo)

- Tailwind 4 + tokens en `frontend/src/index.css`, Zustand, Radix Dialog, ECharts (carga perezosa), Inter autoalojada, Vitest (16 pruebas en verde: `pnpm test`).
- Estructura: `src/app/` (Shell, TopBar, NavRail, Briefing, MapStage, ErrorBoundary, Logo), `src/ui/` (Button, Tag, Dialog, Field), `src/data/` (DataSource/LocalSource + tipos del manifiesto), `src/store/` (ui, history), `src/features/history/` (área, serie, estadística, CSV, PNG, rampa cividis, Heatmap, AnomalyCard, MonthChart, MethodDialog, CalendarPanel, CalendarDock), `src/map/Globe.tsx` (Cesium + OSM).
- Calendario del reto funcionando con datos reales: mes × año 2012-2026, mediana, anomalía con icono y texto, CSV RFC 4180, PNG y metodología.
- `pnpm check`, `pnpm lint`, `pnpm test`, `pnpm build` y `check:size` en verde. Presupuesto de JS inicial subido de 260 a 300 KB en `tools/check-size.mjs` (hay que decirlo en el PR).
- E2E (`CHROME_PATH=/usr/bin/chromium pnpm test:e2e`): 16 en verde y **4 en rojo**:
  - móvil: el briefing tapa los clics en «Cerrar» y «Abrir el mapa» (el overlay de Radix intercepta el clic: hay que revisar el z-index/tamaño del diálogo en móvil o hacer clic dentro del diálogo).
  - escritorio y móvil: `calendario.spec.ts › un área propia…` sin diagnosticar todavía (mira `test-results/…/error-context.md`).
- ⚠️ **Capturas de regresión visual**: en el índice están borradas `tests/visual/__screenshots__/portada-{escritorio,movil}.png`. El usuario rechazó restaurarlas; **pregúntale** antes de tocarlas. Siguiendo `tests/visual/README.md`, las nuevas referencias (portada y calendario) salen del artefacto `referencias-visuales` del CI.
- Pendiente de la fase: `docs/ux-ruta-de-lanzamiento.md` (7 puntos GO / AÚN NO con evidencia), `frontend/README.md`, mover `docs/PROMPT-FRONTEND.md` y este fichero al commit, y commits separados (deps/tokens, calendario, tests).

## 2. Cambios pedidos por el usuario (nuevos, prevalecen)

**Motor de mapa: MapLibre GL JS en lugar de Cesium** (decisión del usuario). Consecuencias:

- Quitar `cesium`, el `viteStaticCopy` de Cesium, `CESIUM_BASE_URL` y el grupo `cesium/` de `tools/check-size.mjs` (ajusta el presupuesto y avísalo). Valora quitar también `three` y deck.gl si no se usan (deck.gl tiene integración con MapLibre: `@deck.gl/mapbox` `MapboxOverlay`).
- Proveedor: **MapTiler, decidido por el usuario** (sustituye a la regla de «sin tokens» para el mapa). La clave está en `frontend/.env.local` como `VITE_MAPTILER_KEY` (ignorado por git; **nunca la escribas en el repo**). Léela con `import.meta.env.VITE_MAPTILER_KEY`. Para el CI y Pages: variable del repo `VITE_MAPTILER_KEY` (Settings → Secrets and variables → Actions), pasada como `env` al paso `pnpm build` de los jobs build/e2e de `deploy.yml`; ya está creada. Añade `VITE_MAPTILER_KEY=` a `.env.example`. Si falta la clave, alternativa automática sin clave (Esri World Imagery, DEM Terrarium de AWS, OpenFreeMap) con aviso visible. Proveedor como configuración intercambiable.
- Terreno: fuente `raster-dem` + `setTerrain` + capa `hillshade`. Topográfico: curvas de nivel (p. ej. `maplibre-contour`, generadas desde el DEM en el cliente). **El modo topográfico tiene que funcionar de verdad.**
- Diseñar para trabajar sin Internet (no hace falta implementarlo ya): estilo y fuentes por configuración, preparado para teselas locales (PMTiles) y caché offline.

Lista del usuario, numerada como la dio:

1. Texto completamente legible (contraste AA, ≥ 14 px, fondos sólidos tras el texto sobre el mapa).
2. Cambiar el mapa (MapLibre; ver arriba).
3. Quitar neones: nada de brillos ni colores saturados de neón; estilo sobrio.
4. Zona de incendio más focalizada y **por cuadrados (rejilla de celdas)**, no un polígono.
5. Solo incendios: escenarios ciudad (interfaz urbano-forestal) y forestal. Fuera inundación, víctimas múltiples e intermunicipal.
6. Simular vías de escape (rutas de evacuación rotuladas «SIMULADO»).
7. El 2.5D va **dentro** del modo 3D (inclinación/exageración del relieve), no como modo aparte → quedan dos modos: 2D y 3D.
8. Responsive para todo (escritorio ≥ 1920, portátil, tablet táctil, móvil, proyector 1280×720).
9. Iconos por tipo de operativo (autobomba, helicóptero, dron, mando…), no puntos.
10. **Diferenciar fuego real de predicción**: detecciones FIRMS (REAL) y propagación del modelo (PREDICCIÓN / SIMULADO) con estilo, leyenda y rótulo distintos, sin posibilidad de confusión (p. ej. real = celdas sólidas; predicción = trama rayada o contorno discontinuo + rótulo).
11. **Quitar el botón «Abrir el mapa»**: el mapa se carga directamente (con esqueleto mientras carga; MapLibre pesa mucho menos que Cesium, pero cárgalo con `import()` para no romper `check:size`/Lighthouse).
12. En 3D el fuego se adapta al terreno (celdas pegadas al relieve, no un polígono plano).
13. Coordenadas del cursor visibles (lat/lon decimal; MGRS si da tiempo) y altitud.
14. Botón de radio (comunicaciones del operativo; si no se implementa, desactivado con motivo «Próximamente»).
15. El mapa topográfico tiene que funcionar.

**Referencia visual** (`/home/pacodev/Pictures/mapa.jpeg`): vista 3D satelital oblicua con el incendio como superficie de calor pegada al relieve (rampa amarillo→rojo), leyendas de intensidad (kW/m) y altura de llama (m) arriba a la derecha, panel de capas a la derecha con grupos plegables y ojo de visibilidad, selector de mapa base (Satélite) e interruptor «Show Contours», tooltip con lon/lat e intensidad al pasar el cursor, línea de tiempo abajo y escala. Ese es el aspecto objetivo, sin neones.

## 3. Orden recomendado

1. Arreglar los 4 e2e, commit de `feat/shell-calendario` y preguntar por las capturas visuales.
2. (Resuelto) MapTiler: clave en `.env` y `frontend/.env.local` (ambos ignorados). El equipo restringe la clave por dominio y la variable del repo ya está creada.
3. Sustituir Cesium por MapLibre: mapa siempre visible, 2D/3D (2.5D dentro de 3D), satélite, topográfico con curvas, hillshade, coordenadas.
4. Capa de detecciones reales (`frontend/public/data/detections-recent-v1.json`, últimos 90 días) por celdas, y el calendario conectado al mapa (área del mapa ↔ calendario).
5. Escenario de incendio (Sierra Bermeja, Málaga): predicción en celdas, vías de escape e iconos de operativo, todo rotulado SIMULADO.
6. Panel de capas, leyendas, botón de radio, responsive, `docs/ux-ruta-de-lanzamiento.md`, README.
7. PRs pequeños a `main` (pedir permiso antes de hacer push).
