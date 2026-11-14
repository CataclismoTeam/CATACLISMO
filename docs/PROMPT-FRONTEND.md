# Prompt de frontend: CATACLISMO (maqueta WILDFIRE COMMAND)

Copia desde aquí. Contexto de repo tomado de la sesión "Proyecto CATACLISMO setup" y de `frontend/`.

---

## Rol y objetivo

Eres un ingeniero frontend senior especializado en GIS y centros de mando. Construye en `frontend/` el prototipo interactivo de **CATACLISMO**, una plataforma geoespacial de respuesta a emergencias (incendios forestales como escenario principal, más inundaciones, incidentes con múltiples víctimas y apoyo intermunicipal) para NASA Space Apps 2026.

Filosofía (ATAK): **un mapa, una imagen operativa compartida, conciencia situacional completa**. NO es un dashboard de KPIs ni una web corporativa. El mapa ES la aplicación (75-85 % del área de trabajo). Principio: máxima conciencia situacional, mínima complejidad de interacción (lo importante a 1-2 interacciones).

## Estado actual del repo (respétalo)

- Monorepo; frontend en `frontend/` (React 19 + TS + Vite 8). Ya existen `cesium`, `@deck.gl/core`, `@deck.gl/layers`, `three`. Hay `src/App.tsx`, `src/main.tsx`, `src/index.css`, `src/components/Globe.tsx` (parte de ahí, refactoriza si conviene).
- Se despliega **estático** en GitHub Pages con `base` = `/CATACLISMO/`. Nada de servidor propio en el frontend; los assets de Cesium se copian con `vite-plugin-static-copy` (ya configurado, no lo rompas).
- **pnpm siempre** (nunca npm/yarn). Añade lo que falte: `tailwindcss`, shadcn/ui (+ `class-variance-authority`, `clsx`, `tailwind-merge`, Radix), `zustand`, `framer-motion`, `lucide-react`, `echarts` (+ `echarts-for-react` solo si hace falta), fuente Inter o Geist (autoalojada, sin CDN).
- El CI exige (y NO debes romper): `pnpm format:check`, `pnpm check` (tsc), `pnpm lint` (oxlint), build, enlaces, html-validate, **presupuesto de peso** (`check:size`), Lighthouse, e2e y regresión visual con Playwright. Haz code-splitting: carga Cesium/deck.gl/echarts con `import()` perezoso y mantén la portada ligera. Si el peso o las capturas visuales cambian a propósito, actualízalos y dilo.
- No uses tokens secretos en el cliente. **No uses Cesium Ion** (requiere token). Usa imagería y terreno sin clave (ver "Motores de mapa"). Los datos son híbridos (ver "Decisiones confirmadas"): cada dato lleva rótulo "REAL" o "SIMULADO". Prohibido aparentar conexión en vivo. El indicador de conexión muestra "Demo / sin conexión a backend", salvo que el usuario conecte `/ws`.
- Idioma de la UI: español (textos y comentarios en español, identificadores en inglés).

## Reto oficial NASA Space Apps 2026: "Harmonization of MODIS and VIIRS Hot Spots" (núcleo de la demo)

Fuente: página del reto (Detalles y Recursos). Dificultad Intermedia/Avanzada; temas Ciencias de la Tierra y Software. Recurso NASA indicado: **FIRMS (NASA Earthdata)**.

Qué pide el reto, resumido:

- Construir una **aplicación web** con un **calendario de actividad de fuego** basado en puntos calientes (hotspots) activos, que combine la serie histórica de **MODIS** (más de dos décadas, Terra/Aqua, en fin de vida) con la continuidad y mayor detalle de **VIIRS**, de forma que "el sensor de origen deje de importar" y el foco sean patrones, tendencias y anomalías.
- Dos partes: (1) **armonización** MODIS+VIIRS; (2) **web** donde el usuario elige una región y un rango de fechas y obtiene analítica y visualizaciones.
- El calendario muestra el **número de detecciones desde principios de los 2000 hasta hoy (con los datos locales, desde 2012)**, para ver qué periodos del año y qué años tienen más fuego y **comparar el mes actual con la mediana histórica** de la zona.
- Sugerencias: **rampas de color accesibles** (para similitudes/diferencias entre meses), **CSV descargable** de las detecciones de la búsqueda, mapa interactivo para **dibujar el área de interés** o introducir latitud/longitud, comparaciones históricas y **anomalías frente a promedios plurianuales**, número de incendios detectados.
- Público: respuesta temprana y emergencias, científicos, gestores del territorio y bomberos.

**Consecuencia de diseño:** el calendario y la armonización son el **eje de la demo**; el mapa 2D/3D/2.5D y el escenario de incendio sirven de contexto y de navegación del calendario. Todo el producto debe poder contarse en una frase: "dibuja un área y ve, mes a mes desde 2000, cuánto ha ardido y si este mes es anómalo".

### Calendario de actividad de fuego (requisitos)

- **Ubicación en la UI:** panel inferior **ampliable** junto a la línea de tiempo, desplegable sobre el mapa. Al pulsar un mes o un año, el mapa y la línea de tiempo saltan a ese periodo y muestran las detecciones; el área sigue la selección actual.
- **Vista principal:** mapa de calor **mes × año (2012 → hoy con los datos actuales)** con número de detecciones armonizadas, **rampa de color accesible** (perceptualmente uniforme, apta para daltonismo, p. ej. viridis/cividis o una secuencial de tintas) y **valor numérico visible** en cada celda o al pasar el cursor; leyenda con escala y unidades. Fila/columna de totales por año y por mes.
- **Comparativa con la mediana histórica:** indicador del mes actual frente a la **mediana de ese mes** en el área, con **anomalía** en % y en número, etiqueta textual ("Muy por encima", "Por encima", "Normal", "Por debajo") e icono; nunca solo color. Gráfico de ECharts de la serie del mes con la banda de mediana/percentiles. Aviso claro si el mes en curso está incompleto.
- **Vistas complementarias** (si hay tiempo): perfil estacional (media por mes con percentiles), serie anual, y ranking de meses/años con más actividad.
- **Selección de área de interés:** dibujar polígono o rectángulo en el mapa (herramienta ya prevista), más campos de latitud/longitud con radio como alternativa de teclado. Mostrar área en km² y recuento de celdas incluidas. Rango de fechas editable (por defecto toda la serie).
- **Salidas:** botón **Descargar CSV** (detecciones/conteos del área y fechas buscadas, con columnas de mes, año, sensor de origen, conteo bruto, conteo armonizado, método y versión) y botón **Descargar PNG** de las visualizaciones (calendario y gráficos). Estados de carga, error y vacío con mensajes humanos.
- **Transparencia metodológica:** panel "Cómo se armonizan los datos" accesible desde el calendario, con fuente (FIRMS MODIS C6.1 y VIIRS S-NPP/NOAA-20), periodo de solapamiento usado para calibrar, factor aplicado, limitaciones (resolución 1 km vs 375 m, horarios de paso, falsos positivos) y fecha del último dato. Marca clara de qué parte de la serie viene de MODIS, VIIRS o ambos.

### Armonización MODIS + VIIRS (enfoque confirmado)

- **Preproceso reproducible fuera del navegador** (script en `tools/` o `scripts/`, en Python con `uv`; documentado): lee detecciones de FIRMS, **calibra VIIRS respecto a MODIS usando los años en que ambos coexisten** (p. ej. 2012-hoy; el método exacto —razón de conteos por celda/estación, regresión, o normalización por cuantiles— debe justificarse y documentarse), y genera **agregados mensuales por celda** de la rejilla.
- **Cobertura:** los datos locales cubren **toda España** (ver tabla); **confirmado: España completa en rejilla de ~5 km**, conteos mensuales 2012 → hoy. **Confirmado también:** serie desde 2012 declarada en la interfaz (el script admite añadir MODIS 2000-2011 más adelante) y filtro por defecto `type = 0`, sin VIIRS `l` ni MODIS con confianza < 30, configurable. Formato compacto (p. ej. JSON/binario tipado por celda con metadatos) que entre en el presupuesto de peso del CI; carga perezosa. La web **solo lee y agrega las celdas** del polígono al vuelo; no calcula la armonización en el navegador.
- **Datos en bruto: ya están en local** (carpetas sin trackear en la raíz del repo, descargadas de FIRMS el 2026-11-14), **no hay que simular nada**:

  | Carpeta                                    | Producto                          | Contenido         | Registros | Periodo                 |
  | ------------------------------------------ | --------------------------------- | ----------------- | --------- | ----------------------- |
  | `DL_FIRE_M-C61_848262/fire_archive_*.json` | MODIS C6.1 (estándar, Terra+Aqua) | archivo histórico | 61 559    | 2012-01-20 → 2026-08-30 |
  | `DL_FIRE_M-C61_848262/fire_nrt_*.json`     | MODIS C6.1 NRT                    | casi tiempo real  | 736       | 2026-09-01 → 2026-11-02 |
  | `DL_FIRE_SV-C2_848263/fire_archive_*.json` | VIIRS S-NPP C2 (estándar)         | archivo histórico | 246 014   | 2012-01-20 → 2026-07-31 |
  | `DL_FIRE_SV-C2_848263/fire_nrt_*.json`     | VIIRS S-NPP C2 NRT                | casi tiempo real  | 6 781     | 2026-08-01 → 2026-11-02 |

  Área: **toda España** (lat 27.6–43.7, lon −18.1–4.3, incluye Canarias y Baleares), no solo Andalucía. Cada registro: `latitude, longitude, acq_date, acq_time (UTC, HHMM), brightness, bright_t31, scan, track, frp, confidence, daynight, satellite, instrument, version, type`.
  - **Limitación crítica:** los archivos empiezan en **2012-01-20**, no en 2000. El calendario cubrirá **2012 → hoy** (≈14,8 años) y debe decirlo en la interfaz y en la metodología ("serie disponible desde 2012; MODIS anterior a 2012 pendiente de descarga"). El script debe aceptar archivos MODIS de 2000-2011 si se añaden más tarde, sin cambios en la web. Como MODIS y VIIRS **coinciden todo el periodo**, la calibración puede hacerse con 14 años de solapamiento.
  - **Empalme archivo + NRT:** unir `archive` y `nrt` sin duplicar ni dejar huecos (el NRT empieza donde acaba el archivo). Marcar los meses con NRT como **provisionales**, porque el procesado estándar puede cambiar valores y detecciones al consolidarse.
  - **`confidence` no es comparable:** MODIS es numérica 0-100; VIIRS es categórica `l`/`n`/`h`. La armonización debe definir una regla común (p. ej. descartar `l` en VIIRS y confianza < 30 en MODIS, justificada y configurable) y dejarla documentada.
  - **`type`:** 0 = vegetación, 1 = volcán, 2 = otra fuente terrestre estática (industria, gas, etc.), 3 = offshore. Por defecto contar solo `type = 0`, con la opción de incluir las demás; aquí hay un 23 % de VIIRS en `type = 2`, que sesgaría la serie.
  - **Resolución distinta:** MODIS 1 km, VIIRS 375 m; VIIRS genera ~4× más detecciones. Por eso hay que calibrar (razón por celda y mes en el solapamiento) y no sumar directamente. Se puede ofrecer además el conteo **FRP** (potencia radiativa, MW) como segunda métrica.
  - **Los JSON brutos (26 MB y 102 MB) NO se versionan ni se publican:** el de VIIRS supera el límite de 100 MB de GitHub, y `check:size` fallaría. Añadir `DL_FIRE_*/` a `.gitignore` y mover los brutos a `data/raw/` (ignorado). Solo se publican los agregados.

### Formato y transferencia de datos (criterio profesional)

Principio: **los datos brutos se procesan una vez en un script; la web solo recibe agregados pequeños y tipados.** Nunca se envían 300 000 registros al navegador.

1. **Entrada (bruto):** los JSON de FIRMS descargados (FIRMS también ofrece CSV, SHP y KML; es el mismo contenido). Se leen en el script con validación de esquema (campos, rangos de lat/lon, fechas ISO).
2. **Normalización (intermedio, local, no versionado):** tabla única en **Parquet** (columnar, comprimido, tipado, estándar de la industria de datos) con las columnas comunes y un campo `sensor`. Se puede leer con DuckDB o pandas/polars. Si se quiere simple, CSV UTF-8, pero Parquet es el formato profesional.
3. **Agregado (salida publicada, en `frontend/public/data/`):**
   - **Rejilla de ~5 km** (p. ej. índice de celda en una rejilla regular en grados, 0,05°), conteos **mensuales por celda y sensor**, ya calibrados.
   - Formato compacto: un **JSON** de metadatos + manifiesto (`manifest.json`: versión, fecha de generación, fuente, método, rejilla, rango temporal, checksum) y los conteos como **binario tipado** (`Uint16Array`/`Uint32Array`) o JSON denso en arrays planos, **comprimidos con gzip/brotli** (GitHub Pages sirve gzip). Objetivo: **< 5 MB** en total para toda España; carga perezosa; trocear por año si hace falta.
   - Nombres y versión inmutables (`hotspots-grid-v1.json`) para que la caché del navegador funcione.
4. **Capa de mapa (detecciones recientes):** **GeoJSON** (o `FlatGeobuf`/binario para deck.gl) solo de los últimos 30-90 días y de la zona visible, con los campos mínimos (`lat, lon, fecha-hora UTC, sensor, frp, confianza`). Nunca el archivo histórico completo.
5. **Salida al usuario (descarga):** **CSV conforme a RFC 4180**, UTF-8 con BOM (para que Excel lo abra bien), separador coma y punto decimal, fechas **ISO 8601 en UTC**, una fila por mes/celda o por detección según lo elegido, y cabecera de metadatos en un fichero acompañante `LEEME.txt` o en comentarios (`# fuente: NASA FIRMS`, `# método`, `# versión`, `# área`, `# generado`). Columnas: `fecha, anio, mes, lat, lon, sensor_origen, conteo_bruto, conteo_armonizado, frp_mw, confianza, tipo, provisional`. Nombre de fichero con área y fechas.
6. **Reproducibilidad:** script `tools/build-hotspots` (Python con `uv`) con argumentos (`--in`, `--out`, `--bbox`, `--cell-km`), semilla fija, registro de cuántos registros se descartan y por qué, y una prueba que verifique la suma de conteos (bruto = armonizado antes de calibrar) y que ninguna celda sale del bbox.
7. **Atribución y licencia:** citar "NASA FIRMS / LANCE, MODIS Collection 6.1 y VIIRS S-NPP Collection 2" y el aviso de uso de los datos NASA en el pie de la app y en la metodología.

## Decisiones confirmadas (prevalecen sobre cualquier otra parte de este prompt)

- **Prioridad por el reto:** (1) calendario de actividad armonizado con selección de área, mediana histórica, anomalía y CSV; (2) los tres modos de mapa como contexto del área y de las detecciones; (3) escenario de incendio forestal; (4) capas y línea de tiempo. Esto sustituye al orden de prioridad anterior.

- **Plazo: menos de 48 horas.** Recorta alcance respetando la prioridad del reto (calendario primero). Los escenarios de inundación, múltiples víctimas e intermunicipal quedan como esbozo navegable (mismos componentes, pocos datos) y la pantalla dividida y el análisis avanzado son opcionales si sobra tiempo.
- **Equipo:** una sola persona con Claude, en una rama de feature; PRs pequeños y frecuentes a `main` (protegida).
- **Audiencia:** jurado en pantalla grande, jurado probando solo en portátil y usuarios de emergencias. Por tanto: briefing inicial, flujo guiado de incendio ("Visita guiada" de 5 pasos, saltable) y sin necesidad de explicación oral.
- **Zona de demo:** Sierra de Málaga (p. ej. entorno de Sierra Bermeja / Ronda / Axarquía), con relieve marcado y un incendio ficticio verosímil.
- **Datos:** híbridos y siempre etiquetados con su origen y fecha.
  - **Reales (snapshots estáticos dentro del repo, sin claves en el cliente):** agregados mensuales armonizados de FIRMS (MODIS/VIIRS) para Andalucía en rejilla de ~5 km (ver sección del reto; origen de datos pendiente) y, para el mapa, un snapshot de detecciones recientes de la zona; meteorología de Open-Meteo; elevación abierta (Terrarium/SRTM).
  - **Simulados:** unidades, incidentes activos, perímetros, sectores, recursos. Rótulo visible "SIMULADO" en esos datos y "REAL · FIRMS · fecha" en los reales. Nunca aparentar tiempo real.
  - Consultas en vivo a Open-Meteo solo si no requieren clave y con fallback automático al snapshot y mensaje claro.
- **Backend:** solo frontend. Interfaz `DataSource` con `LocalSource` (JSON) lista para sustituirse por FastAPI/WebSocket más adelante; no conectar al backend ahora.
- **Dispositivos a garantizar:** escritorio ≥ 1920 px, tablet táctil, móvil (un panel a la vez) y proyector 1280×720 (rótulos y estados legibles a distancia).
- **Identidad:** marca **CATACLISMO** sin "WILDFIRE COMMAND"; descriptor: "Plataforma de mando para emergencias". Logotipo: isotipo simple propio en SVG si no hay uno.
- **Tema:** solo oscuro, con variante opcional de alto contraste / modo proyección (texto grande). Sin tema claro.

## Requisito estrella: tres modos de mapa claramente diferenciados

Un único motor (**CesiumJS**, sin segundo motor de mapas). Un conmutador de modo siempre visible (segmented control en la barra superior + atajos `1`/`2`/`3`) cambia entre tres modos que deben **verse y sentirse distintos de un vistazo** (no solo un cambio de cámara):

| Modo                 | Escena Cesium                                                                                               | Cámara                                           | Imagería / estilo                                                                                                                                                                               | Para qué                                           |
| -------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| **2D**               | `SceneMode.SCENE2D` (plano cenital)                                                                         | Sin inclinación ni rotación libre, solo pan/zoom | Cartografía plana tipo ATAK: mapa base oscuro/callejero, símbolos tácticos grandes y planos, rejilla de coordenadas, cuadrícula MGRS/lat-lon, escala                                            | Táctica y coordinación rápida, tablets rugerizadas |
| **3D**               | `SceneMode.SCENE3D` (globo)                                                                                 | Inclinación y rotación libres, vuelos suaves     | Satélite realista + terreno 3D con relieve, edificios 3D, atmósfera, sombreado por sol/hora, iluminación del globo                                                                              | Entender el terreno, humo/viento, cámaras presets  |
| **Topográfico 2.5D** | `SceneMode.COLUMBUS_VIEW` o 3D con cámara fija inclinada (decide y justifica; prefiere lo que mejor se vea) | Inclinación fija ~45-60°, rotación limitada      | Estilo cartografía topográfica: curvas de nivel, sombreado de relieve (hillshade), tintas hipsométricas, pendiente y orientación, exageración de relieve ajustable (1x-3x), perfil de elevación | Análisis de terreno, accesos, líneas de defensa    |

Reglas de diferenciación:

- Cada modo tiene su **propio conjunto de capas por defecto** y su propio estilo de símbolos (2D: planos/alto contraste; 3D: con altura y sombra; 2.5D: sobre tintas topográficas).
- Transición animada breve (≤ 600 ms) al cambiar de modo, **conservando centro, zoom y selección**.
- Indicador persistente del modo activo (chip con icono) y de la brújula/inclinación; en 2D se oculta el control de inclinación.
- Split-screen: comparar dos modos o dos instantes lado a lado (p. ej. 2D vs 3D, o ayer vs hoy) con cámaras sincronizables. Si dos instancias de Cesium pesan demasiado, usa dos `Viewer` ligeros con carga perezosa y avisa del coste.

## Motores de mapa

- **CesiumJS**: motor principal (globo, escenas, terreno, cámara, entidades, perímetros, línea de tiempo `Clock`).
- **deck.gl** (`@deck.gl/layers`, integra con Cesium mediante capa/overlay): mapas de calor de intensidad de fuego, detecciones MODIS/VIIRS (`ScatterplotLayer`), flechas de viento (`IconLayer`/`PathLayer`), trayectorias de unidades.
- **Three.js**: solo para elementos 3D a medida (columna de humo, helicópteros/drones animados, volúmenes de alcance) cuando aporte; si no, no lo uses.
- Imagería y terreno **sin clave**: satélite (Esri World Imagery o equivalente de uso permitido), topográfico (OpenTopoMap o similar), base oscura. Terreno: proveedor abierto sin token (p. ej. Terrarium/Mapzen en AWS vía `CesiumTerrainProvider`/provider equivalente) o, si no funciona, elevación simulada claramente marcada. Cita las atribuciones en un pie discreto. Verifica licencias y avisa si alguna proveedor limita el uso en producción.
- Zona de demostración: un área montañosa mediterránea con relieve marcado (propón una; p. ej. sierra del interior de la península ibérica) con datos inventados y rotulados.

## Diseño visual

- Interfaz **oscura**: carbón, grafito, azul-gris oscuro. Acento azul para navegación y controles.
- Rojo/naranja/amarillo = fuego; verde = zonas seguras y recursos disponibles; cian/azul = tiempo y agua.
- Bordes sutiles, sombras contenidas, tipografía compacta pero nunca menos de 14 px en texto principal (Inter/Geist, máximo 3 familias), iconos **Lucide**, cero decoración innecesaria.
- Evita: tarjetas y KPIs en exceso, grandes vacíos, titulares enormes, estética de marketing, degradados y glassmorphism, animaciones gratuitas.
- Define tokens de diseño (CSS variables + Tailwind theme) para color, radios, densidad y z-index. Soporta modo de alto contraste y tamaños táctiles ≥ 44 px en el modo tablet.

## Estándar de calidad profesional (transversal)

El resultado debe parecer producto de un equipo de diseño e ingeniería senior, no una maqueta de hackatón:

- **Sistema de diseño real**: tokens (color, espaciado en escala de 4 px, radios, elevación, z-index, movimiento) en un único lugar; componentes base de shadcn/ui personalizados (Button, Toggle, Tabs, Slider, Tooltip, Dialog, Drawer, ContextMenu, Command) con todos sus estados: normal, hover, foco, activo, desactivado, carga, error. Nada de estilos sueltos en los componentes de las pantallas.
- **Pulido visual**: rejilla coherente, alineaciones exactas, densidad de información alta pero ordenada, jerarquía tipográfica de 4-5 tamaños, iconografía Lucide con trazo uniforme (1.5 px) y tamaños fijos (16/20/24). Microinteracciones útiles de 120-200 ms (foco, apertura de paneles), `prefers-reduced-motion` respetado.
- **Simbología cartográfica cuidada**: set propio de símbolos operativos (SVG optimizados, sprite único) con variantes por estado y por modo de mapa, leyendas generadas desde el registro de capas, escala y norte siempre coherentes.
- **Rendimiento**: 60 fps al mover el mapa con las capas por defecto; carga inicial con esqueleto en < 2 s en red rápida; teselas y capas pesadas bajo demanda; sin renders innecesarios (selectores de Zustand granulares, `memo` donde se mida beneficio).
- **Accesibilidad**: WCAG 2.2 AA, navegación completa por teclado, roles y etiquetas ARIA en paneles, menús y herramientas, `lang="es"`, orden de foco lógico, atajos listados en un diálogo de ayuda (`?`).
- **Calidad de código**: TypeScript estricto, módulos pequeños con una responsabilidad, nombres claros, sin código muerto ni `console.log`, comentarios en español solo donde expliquen el porqué, pruebas de la lógica no trivial (stores, conversiones de coordenadas, registro de capas), commits convencionales (el repo usa release-please).
- **Documentación breve**: `frontend/README.md` con arquitectura, cómo añadir una capa o un caso de uso, y las fuentes y licencias de datos y mapas.
- **Copy profesional**: textos en español neutro, concisos y operativos (verbos de acción, sin exclamaciones ni tono publicitario), unidades y formatos consistentes (UTC, metros, km/h, coordenadas decimales y MGRS).

## Layout (map-first)

1. **Barra superior**: identidad CATACLISMO, operación activa, selector de modo 2D/3D/2.5D, fecha-hora (huso UTC visible), centro de notificaciones, usuario y rol, estado de conexión, rótulo "DATOS SIMULADOS".
2. **Navegación compacta** (rail vertical o pestañas finas): Operaciones, Incidentes, Unidades, Entorno, Terreno, Análisis, Histórico. No debe quitar mapa útil.
3. **Barra flotante izquierda**: seleccionar, mover, punto, polígono, línea, medir distancia, medir área, crear ruta, marcador operativo, buscar lugar (por nombre o coordenadas).
4. **Mapa central**: pantalla completa, con perímetros de fuego, detecciones activas, unidades, capas meteorológicas y ambientales; cursor con coordenadas, altitud y escala.
5. **Panel derecho contextual**: gestor de capas (grupos desplegables, visibilidad, opacidad, leyenda, orden con arrastrar y soltar) y ficha del objeto seleccionado con acciones rápidas.
6. **Línea de tiempo inferior**: reproducir/pausar, velocidad, selector de fecha-hora, historial del incidente, comparación temporal.
7. Paneles **colapsables y redimensionables** (persistir tamaños en `localStorage` con try/catch).

## Módulos y capas

Módulos: **Operaciones** (incidentes, unidades, sectores de mando, zonas seguras/restringidas/evacuación, puntos de reunión, centros médicos, puntos de agua), **Incidentes** (ficha detallada sin salir del mapa: ubicación, clasificación, gravedad, estado, unidades asignadas, perímetro, cronología, fotos/informes, notas geográficas), **Unidades** (autobombas, ambulancias, rescate, mando, helicópteros, drones, equipos de campo, parques, hospitales; cada uno con ID, posición, estado, equipo, última actualización, disponibilidad; símbolos operativos tipo APP-6/ATAK, no pines genéricos), **Entorno** (temperatura, humedad, viento en velocidad/dirección/altura, precipitación, humedad del suelo, vegetación, combustibles, fauna, hábitats protegidos), **Terreno** (elevación 3D, pendiente, orientación, curvas de nivel, valles y crestas, pistas forestales, accesibilidad, perfil de elevación, medidas), **Análisis** (gráficos ECharts: perfil de elevación, rosa de vientos, evolución del perímetro, recursos por estado), **Histórico** (detecciones MODIS/VIIRS, calendario de actividad, comparativas, anomalías, perímetros por fecha, meteorología histórica, reproducción temporal).

Gestor de capas, grupos expandibles: **Fuego** (detecciones activas, MODIS, VIIRS, perímetros, intensidad, incidentes históricos) · **Unidades** (bomberos, autobombas, ambulancias, rescate, mando, drones) · **Entorno** (temperatura, humedad, viento, precipitación, humedad del suelo) · **Terreno** (elevación, pendiente, orientación, curvas, accesibilidad) · **Vegetación y fauna** (cobertura forestal, combustibles, especies, hábitats) · **Infraestructura** (carreteras, edificios, parques, hospitales, hidrantes, depósitos, accesos de emergencia). Cada capa: visibilidad, opacidad, configuración contextual. Diseña el modelo de datos para soportar ~31 casos de uso: **configuración declarativa** (un registro de "casos de uso" que activa capas, módulos, plantilla de ficha y símbolos), no pantallas hardcodeadas.

## Interacción

Clic para seleccionar, hover con información, menús de acción rápida (clic derecho / pulsación larga), arrastrar y soltar capas, búsqueda por lugar o coordenadas, marcadores guardados, presets de cámara (norte arriba, vista oblicua del incendio, vista desde la unidad), herramientas de medición y dibujo, reproducción temporal, pantalla dividida. Ratón **y táctil** (gestos de pellizco/rotación; objetivos táctiles grandes). Teclado: atajos documentados y foco visible (accesibilidad AA mínima).

## Escenarios de demostración (datos simulados, navegables)

1. **Incendio forestal**: seleccionar el incidente → perímetro, detecciones por satélite, viento (dirección/velocidad), vegetación circundante, parques y unidades cercanas, elevación y accesibilidad, puntos de agua.
2. **Inundación**: áreas afectadas, carreteras cortadas y accesos restringidos, zonas de evacuación, puntos de bombeo, equipos de rescate y ambulancias, zonas seguras de reunión.
3. **Incidente con múltiples víctimas**: ubicación, centros médicos, ambulancias disponibles, puntos de encuentro de pacientes, áreas de triaje y tratamiento, distribución de recursos.
4. **Apoyo intermunicipal**: recursos de varios municipios, sectores operativos, unidades en camino, información compartida, puntos de reunión y mando.

Un selector de escenario cambia datos, capas activas y encuadre de cámara.

## Arquitectura de código

- Estructura sugerida: `src/app/` (shell/layout), `src/map/` (viewer Cesium, modos 2D/3D/2.5D, proveedores de imagería/terreno, puente deck.gl, Three.js), `src/layers/` (registro de capas + grupos), `src/features/` (operations, incidents, units, environment, terrain, analytics, history), `src/store/` (Zustand: modo de mapa, selección, capas, escenario, tiempo, paneles), `src/data/` (JSON/TS simulados con tipos y rótulo de simulación), `src/ui/` (shadcn + componentes propios), `src/lib/`.
- Tipado estricto (TS), sin `any`. Estado global con **Zustand** (slices), animaciones con **Framer Motion** solo para paneles/transiciones funcionales.
- Cesium como singleton montado una vez; los modos cambian `scene.mode`/imagery layers/cámara sin recrear el `Viewer`.
- Preparar (sin obligar) el cliente `ws` para `/ws` del backend FastAPI y la lectura de PostGIS vía API: interfaz `DataSource` con implementación `SimulatedSource`; al conectar el backend se intercambia sin tocar la UI.
- Pruebas: actualizar el e2e de Playwright para comprobar que el shell carga, que el conmutador cambia de modo y que una capa se activa/desactiva. Regenera las capturas de regresión visual solo si cambian a propósito.

## Autoevaluación UX obligatoria ("Ruta de lanzamiento", NASA Space Apps · Ladies That UX Málaga)

La demo se evaluará con esta hoja de 7 etapas. Cada punto es requisito de diseño y de aceptación (⭐ = extra deseable). Si choca con otra instrucción de este prompt, **gana esta lista** (p. ej. "tipografía compacta" nunca baja de 14 px en texto principal).

1. **Propósito a primera vista**: la primera pantalla deja claro qué es y a quién va dirigido (incluye un briefing inicial descartable de 3 líneas: "CATACLISMO · plataforma de mando para emergencias · demo con datos simulados"); lo que más destaca es la acción principal (seleccionar el incidente activo). ⭐ Alguien ajeno lo entiende en 5 s.
2. **Flujo principal**: la tarea clave (incidente → perímetro, viento, recursos y accesos → decisión) se completa de principio a fin; desde cada pantalla/panel se puede seguir o **volver atrás** (botón Atrás/Esc, migas de pan). ⭐ Se sabe en qué paso se está (indicador de escenario/paso).
3. **Jerarquía y patrones**: una acción principal por pantalla, lo secundario más discreto; botones, tarjetas y menús idénticos en todas las pantallas (un único componente de cada). ⭐ Patrones conocidos: lupa = buscar, X = cerrar, engranaje = ajustes.
4. **Legibilidad**: texto principal ≥ 14 px; botones y títulos en lenguaje de quien lo usa (bombero, coordinador), sin jerga técnica ("Capas", no "Overlays layer registry"). ⭐ Máximo 3 tipografías (p. ej. Inter + una mono para coordenadas).
5. **Contraste y color**: contraste AA del texto sobre su fondo, también con brillo bajo (clave en tema oscuro y sobre el mapa: usa fondos sólidos tras el texto flotante); **nada depende solo del color** (estado de unidad = color + icono + texto: "Disponible", "En ruta", "No disponible"; fuego, zona segura y evacuación con patrón o icono además del color). ⭐ En escala de grises todo se sigue entendiendo (pruébalo con `filter: grayscale(1)`).
6. **Tamaños para pulsar**: botones y enlaces pulsables con el dedo (≥ 44×44 px en táctil), separación suficiente para no pulsar el de al lado (≥ 8 px). ⭐ Legible a 2 m con el portátil sobre la mesa (rótulos clave y estados en tamaño grande, modo "proyección").
7. **Respuesta del sistema**: cada acción tiene respuesta visible (cambio, mensaje o indicador de carga: skeletons y spinners al cargar teselas, terreno y capas); los errores dicen **qué ha pasado y cómo seguir** ("No se pudo cargar el terreno. Usamos elevación simulada. Reintentar"); ⭐ las pantallas vacías dicen qué hacer ("Sin unidades en esta zona. Activa la capa Unidades o amplía el área").

**Alerta roja: que NO aparezca en la demo** (revisión final obligatoria, barrido de código y de pantalla):

- Textos o datos de relleno: "lorem ipsum", "Título aquí", "asdf". Todos los datos simulados deben ser plausibles y rotulados.
- Botones que no hacen nada en el flujo que se va a enseñar: si una herramienta no está implementada, no se muestra o aparece desactivada con motivo explicado ("Próximamente"), nunca muerta.
- Errores técnicos a la vista ("Error 500", "undefined", "NaN", trazas): captura todo en un `ErrorBoundary` y mensajes humanos.
- Estados que solo se distinguen por el color, sin texto ni icono.

Añade una checklist en `docs/ux-ruta-de-lanzamiento.md` con los 7 puntos marcados GO / AÚN NO y la evidencia (captura o ruta del componente) de cada uno, y un test e2e de Playwright que falle si aparece `undefined`, `NaN`, `lorem` o `Error 500` en el texto visible de las pantallas del flujo principal.

## Entregables y criterios de aceptación

0. **Reto cumplido:** se dibuja un área, se ve el calendario mes×año 2000→hoy con rampa accesible, se compara el mes actual con la mediana histórica con anomalía en texto e icono, se descarga CSV y PNG, y se explica la metodología de armonización. Sin datos reales aún, queda claramente rotulado como simulado.
1. `pnpm dev` muestra el shell completo con los tres modos funcionando y visualmente distintos.
2. Capas con visibilidad y opacidad funcionales; líneas de tiempo con reproducción real sobre los datos simulados.
3. Los 4 escenarios navegables; ficha contextual al seleccionar cualquier objeto.
4. Usable en monitor de sala de mando (≥1920 px) y en tablet (≥ 1024 px, táctil); degradación razonable en móvil.
5. Pasan todas las comprobaciones locales del README (`format:check`, `check`, `lint`, build, links, html, size, e2e).
6. Los 7 puntos de la Ruta de lanzamiento en GO (con sus obligatorios) y la alerta roja limpia.
7. Cumple el "Estándar de calidad profesional": sistema de diseño único, estados completos en cada componente, AA de accesibilidad y 60 fps con las capas por defecto.
8. Sin Ion, sin tokens, sin CDN externos de fuentes/scripts; atribuciones de mapas visibles; todo dato rotulado como simulado.

## Forma de trabajar

Antes de escribir código, propón en 10 líneas el plan por fases (1: shell + store + tokens; 2: mapa y 3 modos; 3: capas y panel; 4: unidades/incidentes; 5: línea de tiempo y análisis; 6: escenarios, split-screen y pulido). Entrega por PRs pequeños a rama de feature (nunca directo a `main`, que está protegida con 10 checks y squash). Pregunta solo lo que cambie el resultado; el resto, decide y anótalo.

---

## Pendientes de decisión (para quien lo ejecute)

- Terreno sin clave: confirmar proveedor en pruebas reales (si falla, elevación simulada).
- 2.5D: Columbus View vs 3D inclinado fijo; elegir tras comparar en pantalla.
- Zona geográfica de la demo.
