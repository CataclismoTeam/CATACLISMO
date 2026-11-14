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
backend/    API FastAPI (uv): app/main.py, app/db.py (PostGIS), app/ws.py (WebSockets)
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
