# Seguimiento de CATACLISMO

Estado a 15 nov 2026, 10:30 (último commit en `main`: `9f91cae`). Hoja de ruta de lo que falta:
[MEJORAS.md](MEJORAS.md).

## Resumen

| Parte                     | Estado                                              |
| ------------------------- | --------------------------------------------------- |
| Datos y armonización      | ✅ Hecho                                            |
| Front v2 (mapa y paneles) | ✅ Hecho y publicado (`ea69cbe`, Deploy verde)      |
| Mejoras de MEJORAS.md     | ⏳ Bloque 0 hecho; bloques 1 a 5 hechos; 6 a medias |
| Deploy de `main` ahora    | ❌ Roto por el último merge del backend             |

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

## Problema abierto: Deploy roto en `main`

El merge del backend (`9f91cae`, rama `back`) rompe el Deploy, así que la web no se actualiza.
Sigue publicada la versión buena (`ea69cbe`). Lo que falla:

- **Guardián**: hay 3 ficheros por encima de 1 MB versionados:
  `backend/checkpoints/best_model.keras`, `backend/checkpoints/latest_backup.keras` y
  `backend/app/lucia/artifacts/routes/lucia_routes.geojson`. Los modelos deberían ir fuera de git
  (o en Git LFS o un release) y el GeoJSON, comprimido o recortado.
- **Backend**: `ruff` encuentra 450 errores en el código nuevo.
- **Secretos**: `gitleaks` detecta 1 posible secreto en el historial. Hay que revisarlo y rotarlo
  si es real.

Esto es del backend: lo arregla quien lo subió, o se acuerda en el equipo antes de tocarlo.
