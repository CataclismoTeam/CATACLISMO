# Mejoras del front v2 (solo frontend)

Hoja de ruta de las mejoras que no tocan el backend. Cada bloque va en su propio commit y se
sube a `main`. Marca la casilla al terminarlo.

## Contexto

El front v2 ya está en `main`: mapa MapLibre, incendios reales por comunidad autónoma, 12
simulaciones, unidades por aire, tierra y mar, vías de escape y ajustes. Las cuatro mejoras
elegidas son la línea de tiempo del fuego, la conexión entre el calendario y el mapa, los avisos
de pueblos en riesgo, y buscar, medir y compartir. Antes hay que cerrar lo pendiente, porque el
Deploy está en rojo.

## Bloques

- [x] **0 · Cerrar lo pendiente**
  - Fuego real y simulado en celdas sólidas de 250 m (`map/overlays.ts`; `fireCells` en
    `map/detections.ts`, que marca las celdas que cubre cada píxel; leyenda en
    `map/LayersPanel.tsx`).
  - `tests/visual/portada.spec.ts`: esperar a `#calendario-titulo` y no a `table` (en móvil el
    calendario empieza plegado).
  - Deploy en verde y capturas de `referencias-visuales` revisadas y subidas.

- [x] **1 · Línea de tiempo del fuego**
  - Store `store/ui.ts`: `fireHour` (0–6) y `playing`.
  - `map/FireTimeline.tsx`: reproducir y pausar, deslizador de 0 a 6 h y la hora (`T+2 h`). Solo
    con una simulación visible y de cerca.
  - `overlays.ts`: `inc-fill` e `inc-line` muestran `horas <= fireHour` (lo que ya ha ardido) y la
    predicción, `horas > fireHour`. Función `applyFireHour(map, h)` con `setFilter`.
  - Reproducción con `requestAnimationFrame` (6 h en unos 12 s). Con `prefers-reduced-motion`,
    salta por pasos.

- [x] **2 · Calendario ↔ mapa**
  - Mes seleccionado → capa `mes-celdas` con la rejilla de 5 km de ese mes (`useHistory`: `grid` y
    `selected`; celdas con `cellCenter` de `features/history/area.ts`, valor `h`). Rótulo
    «REAL · FIRMS · mes año». Interruptor en el panel de capas: «Actividad del mes del
    calendario».
  - «Dibujar área» en el calendario (`AreaForm.tsx`): dos clics en el mapa forman un rectángulo
    → `setArea({ kind: 'bbox', ... })`. Estado `drawing` en el store.
  - El área del calendario se dibuja en el mapa y el mapa la encuadra (`flyTarget`).

- [x] **3 · Avisos de pueblos en riesgo**
  - `map/AlertsPanel.tsx`: tercer panel izquierdo («Avisos», en el rail y en la barra) con los
    núcleos de la simulación activa (`escape-routes-v1.json`), ordenados por `llegadaFuegoMin`.
  - Nivel según el margen: crítico (< 30 min), alto (< 90 min) y vigilancia (el resto). Icono,
    texto y color.
  - Pulsar un aviso encuadra su ruta y la resalta. El botón del rail muestra cuántos avisos
    críticos hay.

- [x] **4 · Buscar, medir y compartir**
  - **Buscar**: caja en la barra superior. Las coordenadas «lat, lon» vuelan directas; el texto
    va a la geocodificación de MapTiler
    (`https://api.maptiler.com/geocoding/{q}.json?key=…&country=es&language=es`). Mensaje claro si
    no hay clave o no hay red.
  - **Medir**: regla en el mapa. Los clics forman una línea con su distancia en km (haversine de
    `features/history/area.ts`); al cerrarla, el área en ha o km². Esc cancela.
  - **Compartir**: el estado va en el hash (`#sim=bermeja&inc=INC-001&z=11.5&c=lon,lat&m=3d`), se
    lee al cargar y un botón «Copiar enlace» avisa con «Enlace copiado».

- [x] **5 · Recortes e idioma**
  - Quitar el apartado de mar: solo salvamento por tierra y aire (unidades, radio, leyenda,
    filtros y textos).
  - Interruptor ES/EN: como mínimo briefing, leyendas, avisos y metodología (jurado
    internacional).

- [ ] **6 · Pruebas de rendimiento, red y heurísticas**
  - Rendimiento: Lighthouse también sobre el mapa (no solo la portada con el briefing), en
    escritorio y móvil.
  - Red: e2e con red lenta (3G simulada) y sin red; los JSON que fallan muestran error y
    «Reintentar», no «Cargando…» eterno.
  - Heurísticas: revisión con las 10 de Nielsen (hecha:
    [evaluacion-heuristica.md](evaluacion-heuristica.md), 22 arreglos) y prueba con 3-4 personas de fuera del equipo
    (5 min cada una), centrada en solapes de paneles y en real frente a simulado.

## Verificación (en cada bloque)

- `pnpm format:check`, `pnpm check`, `pnpm lint`, `pnpm test`, `pnpm build`, `pnpm check:size`,
  `pnpm check:links`, `pnpm check:html` y `node tools/guard.mjs`.
- e2e nuevos en `tests/e2e/`, con el mapa en 2D: la línea de tiempo cambia la hora; pulsar un mes
  pinta su capa; dibujar un área cambia el calendario; los avisos se ordenan y encuadran; las
  coordenadas vuelan; medir da km; un enlace con hash restaura la simulación.
- `CHROME_PATH=/usr/bin/chromium pnpm test:e2e` y `CHROME_PATH=/usr/bin/chromium pnpm lighthouse`
  (rendimiento ≥ 0,9).
- Push a `main` y Deploy en verde.

## Pendientes de la auditoría

Ordenados por impacto en la demo. Pasan a bloque cuando se eligen.

### Antes de la demo (rápidas y de mucho impacto)

- [x] **Procedencia real/simulado**: chip fijo arriba, visible también en móvil («Real · FIRMS
      2-nov» o «Simulado»), según lo seleccionado, con un popover que explique cada capa. Hoy «Real ·
      FIRMS» sale desde 1024 px y «Demo» desde 1536 px.
- [x] **Antigüedad del dato**: los datos son del 2-nov. Mostrar «última detección: hace N días» y
      renombrar «Actividad reciente» por algo medible.
- [x] **Halo de incendios reales**: usa un viento fijo inventado y parece pronóstico. Rotularlo
      «Ilustrativa» y poder ocultarlo (o quitarlo).
- [x] **Errores de carga**: estados cargando | listo | error y botón «Reintentar». Si fallan las
      rutas, no decir «no hay núcleos amenazados».
- [x] **Solapes**: la tarjeta del incendio tapa «Capas»; las fichas y la barra de coordenadas
      tapan la lista izquierda. Un contenedor flex por esquina para que las tarjetas se apilen.
- [x] **Enlaces a fuentes**: FIRMS/NASA, MODIS/VIIRS, OpenStreetMap y MapTiler en el briefing, la
      ficha del incendio y la metodología.
- [x] **Monitor roto**: `monitor.yml` comprueba un fichero de Cesium que ya no existe y abre un
      issue falso cada 6 h.
- [x] **Duplicados del merge**: paso de Vitest repetido en `deploy.yml` y clave `"test"` repetida
      en el `package.json` de la raíz.
- [x] Un manejador de clic se duplica cada vez que cambia el mapa base.
- [x] La hora «Actualizado» de las unidades está fija (14-nov 13:20): rotularla «hora de
      simulación».
- [x] Quitar «Entorno» y «Terreno» del menú (botones desactivados).

### Credibilidad científica

- [x] Apartado «Datos y métodos»: fechas de descarga, resolución (375 m / 1 km) y limitaciones.
- [x] Explicar el modelo de propagación: elipse con viento, supuestos y lo que no hace
      (combustible, humedad, pendiente). Leyenda de intensidad.
- [ ] Incertidumbre: tres franjas de probabilidad o un «margen ±».
- [ ] Datos congelados: el cron diario no regenera nada (8 de 232 incendios activos). Automatizar
      o quitar el cron y rotular la fecha del dato. Opción: FIRMS casi en vivo por su API.
- [ ] Clic en detecciones sueltas (6.775 con fecha, sensor y potencia).

### Rendimiento

- [ ] Unos 38.000 polígonos y 8 halos se recalculan en el hilo principal: precalcular en
      `tools/build-hotspots` o mover a un Web Worker.
- [ ] Cascada de descargas: pedir el chunk de MapLibre (1,1 MB) y los 3 JSON en paralelo mientras
      se lee el briefing.
- [ ] Peso: Radix ya quitado y paneles bajo demanda (JS inicial 289,8 KB). Falta sustituir ECharts (513 KB) por SVG o uPlot.
- [ ] Dividir `escape-routes` (177 KB) por escenario y cargar solo el activo.

### Accesibilidad

- [x] Hook único para paneles flotantes (ajustes, radio, capas): foco al abrir, Esc, clic fuera y
      devolver el foco.
- [x] ARIA: quitar `role="radio"` con `aria-pressed`; asociar pestañas de unidades a su panel;
      flechas en grupos.
- [x] Atajos «1» y «2»: desactivables y sin dispararse con el briefing abierto.
- [x] Daltonismo: variar la trama de las tres franjas; repintar el gráfico mensual al cambiar de
      tema.
- [ ] Enlace «Saltar al mapa» hecho; falta sacar del tabulador los 17 botones del mapa.

### Ideas nuevas

- [ ] Modo presentación: recorre los escenarios con cámara automática (demo de 2 min).
- [ ] Informe exportable del incendio (PDF o PNG): mapa, rutas, tiempos y márgenes.
- [ ] Onboarding de 3 pasos la primera vez (capas, unidades, rutas).

### Calidad y CI

- [ ] Vitest solo cubre 1 fichero: modelo de propagación (más lejos ⇒ más horas; sin viento,
      simétrico), `fireCells`, anti-solape de placas y stores.
- [ ] e2e del modo 3D (el predeterminado) y axe-core.
- [ ] Dividir `MapView.tsx`, `scenario.ts` y `overlays.ts` en hooks y módulos.
- [ ] Pre-push con tsc, lint y tests.
- [ ] READMEs del front: aún describen Cesium.
