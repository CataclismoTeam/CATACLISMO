# Seguimiento de CATACLISMO

Estado a 15 nov 2026, 15:50. Hoja de ruta de lo que falta:
[MEJORAS.md](MEJORAS.md).

## Resumen

| Parte                     | Estado                                         |
| ------------------------- | ---------------------------------------------- |
| Datos y armonización      | ✅ Hecho                                       |
| Front v2 (mapa y paneles) | ✅ Hecho y publicado (`ea69cbe`, Deploy verde) |
| Mejoras de MEJORAS.md     | ⏳ Bloques 0 a 5 y 7 hechos; 6 a medias        |
| Backend ↔ front           | ✅ Conectado: CATA, LUCIA y JULI (`5ca0283`)   |
| Deploy de `main`          | ✅ Verde y publicado (`7cd98df`)               |

## Hecho

### Datos (`tools/build-hotspots`)

- Armonización MODIS + VIIRS de NASA FIRMS (2012-2026, toda España, rejilla de 5 km).
- Incendios reales de los últimos 90 días: 232 en 15 comunidades autónomas.
- Vías de escape de las simulaciones con el algoritmo del equipo, sobre carreteras reales de
  OpenStreetMap.

### Front v2 (etiqueta `front-v2.0.0`)

- **Mapa**: MapLibre + MapTiler, 2D y 3D (el 2.5D es el 3D inclinado), satélite y
  topográfico con curvas de nivel.
- **Fuego**: real y simulado en celdas sólidas de 250 m; la predicción, con rayas. De lejos,
  un icono por incendio.
- **Incendios**: lista por comunidad autónoma, ficha en el lateral y 12 simulaciones en 9
  comunidades.
- **Operativo**: unidades por aire, tierra (en grupos) y mar; radio con General Tierra y un canal
  por grupo; avisos de vías de escape.
- **Histórico**: calendario mes × año con mediana, anomalía, CSV, PNG y metodología.
- **Ajustes**: tema sistema, claro u oscuro, modo para daltonismo y modo proyección. Icono propio
  en la pestaña.
- **Calidad**: Lighthouse local con rendimiento 0,93 y el resto a 1; e2e de escritorio y móvil;
  capturas de regresión visual subidas.

## Mejoras (MEJORAS.md)

- [x] **0 · Cerrar lo pendiente**: fuego en celdas, tests visuales y Deploy en verde (`ea69cbe`).
- [x] **1 · Línea de tiempo del fuego**
- [x] **2 · Calendario ↔ mapa**
- [x] **3 · Avisos de pueblos en riesgo**
- [x] **4 · Buscar, medir y compartir**
- [x] **5 · Recortes e idioma** (quitar mar, ES/EN)
- [ ] **6 · Pruebas de rendimiento, red y heurísticas**
- [x] **7 · Backend conectado**: CATA, LUCIA y JULI en el mapa, JULI en vivo por WebSocket

## Backend conectado

La web publicada se conecta sola al backend en Render (`https://cataclismo-api.onrender.com`,
desplegado con `render.yaml` en cada push a `main` que toque `backend/`). La URL va en la
variable del repo `VITE_API_URL`. Si no responde, la app sigue con sus datos estáticos. En
local se usa con `?api=` o Ajustes: [frontend/README.md](../frontend/README.md#conexión-con-el-backend).

- **CATA**: celdas de 1 km por categoría, sacadas de `/api/lucia/routes` (el fichero de
  `/api/cata/predictions` aún no existe en el backend y da 404).
- **LUCIA**: rutas para personas y animales, orígenes en riesgo y puntos de encuentro.
- **JULI**: operarios por estado y aro rojo sin prueba de vida; en vivo por `/ws`.
- Plan gratuito: el servidor se duerme tras 15 min sin uso y la primera visita tarda hasta 1 min
  («Conectando…»). Sin base de datos PostGIS en Render (`/health` da `database: unavailable`).
- Pendiente: que JULI no escriba su estado en ficheros versionados (`backend/app/juli/artifacts/`).

## Deploy de `main`

Los fallos del merge del backend ya están arreglados: guardián con límite propio para los modelos,
ruff a cero, falso positivo de gitleaks ignorado por huella, tests de la API, ruta del algoritmo de
vías de escape y e2e adaptados a las rutas nuevas.
