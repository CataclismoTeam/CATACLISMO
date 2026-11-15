# CATACLISMO

Propuesta del equipo CATACLISMO para NASA Space Apps 2026.

Web publicada: https://cataclismoteam.github.io/CATACLISMO/

## Stack

| Parte               | Tecnología                                                 |
| ------------------- | ---------------------------------------------------------- |
| Interfaz            | React + TypeScript (Vite)                                  |
| Motor geográfico 3D | CesiumJS                                                   |
| Capas geoespaciales | deck.gl                                                    |
| Efectos 3D          | Three.js                                                   |
| Backend             | Python + FastAPI                                           |
| Datos geográficos   | PostgreSQL + PostGIS                                       |
| Tiempo real         | WebSockets (`/ws` en la API)                               |
| CI/CD               | GitHub Actions → GitHub Pages (solo el frontend, estático) |

## Estructura

```
frontend/   React + TS + Cesium (Vite). El build sale a dist/ en la raíz
backend/    API FastAPI (uv): app/main.py, app/db.py (PostGIS), app/ws.py (WebSockets) — cuadrícula unificada 1000×1000 m (EPSG:3035, ES1K); ver backend/README.md (incluye feed NRT con FIRMS_MAP_KEY en secretos del repo)
tests/      e2e y regresión visual con Playwright sobre el build real
tools/      scripts del CI: guardián, enlaces, peso, servidor estático, commits
config/     Playwright, Lighthouse, html-validate, release-please
ops/        página de mantenimiento
```

## Puesta en marcha

Requisitos: Node 26, pnpm 12 (nunca npm ni yarn), uv y Docker.

```bash
pnpm install          # dependencias del frontend y herramientas (instala también los hooks de git)
pnpm dev              # frontend en http://localhost:5173/CATACLISMO/
```

```bash
cp .env.example .env  # y cambia la contraseña
docker compose up     # PostGIS en :5432 y la API en http://localhost:8000 (docs en /docs)
```

API sin Docker (con la base de datos levantada):

```bash
cd backend && uv sync && uv run uvicorn app.main:app --reload
```

## Clave de API de la NASA (`FIRMS_MAP_KEY`)

Para consultar el feed Near Real-Time (NRT) de **NASA FIRMS** (`https://firms.modaps.eosdis.nasa.gov/api/area/csv/...` en [`backend/app/live_nrt.py`](backend/app/live_nrt.py) y el endpoint `POST /api/live/refresh`), el backend **necesita obligatoriamente** la clave `FIRMS_MAP_KEY`:

- **En GitHub / producción:** la clave real está guardada en **GitHub Secrets** (`FIRMS_MAP_KEY`) y nunca se versiona en el repositorio. Cualquier workflow o despliegue que active la ingesta NRT debe inyectarla desde `${{ secrets.FIRMS_MAP_KEY }}`.
- **En local:** cópiala en `backend/.env` (puedes partir de `.env.example`) o expórtala como variable de entorno antes de arrancar `uvicorn` o ejecutar `python -m app.live_nrt`.
- **Comportamiento sin clave:** NASA FIRMS rechaza la petición con `HTTP 400 (Invalid MAP_KEY.)` y el endpoint `POST /api/live/refresh` responde `HTTP 400` indicando que falta `FIRMS_MAP_KEY`. Por su parte, la API **NASA POWER** ([`backend/app/valen/rainfall_client.py`](backend/app/valen/rainfall_client.py)) y **Open-Meteo** no requieren clave.

## Origen de los datos de predicción de CATA y consumo en el frontend

Hay que distinguir entre la **web estática publicada hoy en GitHub Pages** y el **pipeline neuronal del backend**:

1. **Predicciones reales de CATA (`backend/`):**
   - El modelo entrenado **CATA** (`ConvLSTM2D` de 22 canales, `backend/app/cata/artifacts/models/cata_c22.keras`) genera [`backend/app/cata/artifacts/predictions/cata_predictions.json`](backend/app/cata/artifacts/predictions/cata_predictions.json), con matrices 2D por zona (`fire_probability_grid`, `state_matrix`, `estimated_fire_arrival_hours`, costes `human`/`animal`) y `active_and_predicted_cells` (que incluye passthrough de `valen_features_norm`).
   - El backend FastAPI lo sirve en **`GET /api/cata/predictions`** (`backend/app/main.py`) y lo consume **LUCIA** (`lucia_c15.keras`) para generar [`backend/app/lucia/artifacts/routes/lucia_routes.geojson`](backend/app/lucia/artifacts/routes/lucia_routes.geojson), expuesto en **`GET /api/lucia/routes`**, **`GET /api/lucia/meeting-points`** y **`POST /api/lucia/route`** (`POST /api/live/refresh` regenera ambos en caliente cuando hay `FIRMS_MAP_KEY`).
2. **Datos actuales del frontend estático (`frontend/`):**
   - En su estado actual, el frontend desplegado en GitHub Pages **todavía no llama al backend FastAPI** (`frontend/src/data/source.ts` usa únicamente `LocalSource` sobre `frontend/public/data/`).
   - Las detecciones reales de NASA FIRMS (`hotspots-manifest-v1.json`, `hotspots-cells-v1.bin`, `hotspots-grid-v1-*.bin`, `detections-recent-v1.json`, `incidents-v1.json`) proceden del preproceso offline [`tools/build-hotspots`](tools/build-hotspots/README.md).
   - La capa visual rotulada como _SIMULADO / PREDICCIÓN_ y las rutas estáticas (`escape-routes-v1.json`) se calculan con [`frontend/src/map/scenarios.json`](frontend/src/map/scenarios.json) y el modelo elíptico simplificado en el cliente ([`frontend/src/map/scenario.ts`](frontend/src/map/scenario.ts)), a la espera de conectar la UI a `/api/cata/predictions` y `/api/lucia/routes`.

## Comprobaciones locales

```bash
pnpm format:check && pnpm check && pnpm lint
pnpm build && pnpm check:links && pnpm check:html && pnpm check:size
CHROME_PATH=/usr/bin/chromium pnpm test:e2e
cd backend && uv run ruff check . && uv run pytest
```

## Despliegue

Cada push a `main` pasa por [`deploy.yml`](.github/workflows/deploy.yml): 10 módulos de revisión en
paralelo (guardián, calidad, workflows, secretos, dependencias, CodeQL, build, Lighthouse, e2e y
backend). Solo si pasan todos se publica en GitHub Pages, con atestación de procedencia y prueba de
humo. Los PR solo revisan. Modo mantenimiento: _Run workflow → maintenance_ o la variable del repo
`MAINTENANCE_MODE=true`.

Los commits siguen [Conventional Commits](https://www.conventionalcommits.org/es/); release-please
genera las versiones y el CHANGELOG.
