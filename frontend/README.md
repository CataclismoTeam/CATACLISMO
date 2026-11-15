# CATACLISMO frontend

## Desarrollo

Desde la raíz del repositorio:

```bash
pnpm dev
```

Comprobaciones disponibles:

```bash
pnpm --filter frontend check
pnpm --filter frontend lint
pnpm --filter frontend test
pnpm --filter frontend build
```

## Mapa operativo

El mapa se abre bajo demanda para no cargar Cesium en la portada. Incluye modos
2D, 2.5D y 3D, fondos cartográficos, brújula, escenario simulado y gestor de
capas. Desde **Dibujar área** se puede crear un rectángulo con dos clics o un
polígono cerrándolo con doble clic; el área se aplica automáticamente al
calendario inferior.

El panel de capas permite activar perímetro, unidades, viento y detecciones
satélite. Los datos del escenario son simulados y se muestran como apoyo visual,
no como fuente operativa real.

## Conexión con el backend

En la web publicada el front se conecta solo al backend de Render (`render.yaml`, URL en la
variable del repo `VITE_API_URL`). Si no responde, la app sigue con sus datos estáticos. Con la API de
`backend/` en marcha, el mapa añade el grupo **Backend** en Capas:

- **CATA**: predicción neuronal por celdas de 1 km (ardiendo, ya quemado y por encima del umbral).
- **LUCIA**: vías de escape para personas y animales, puntos de inicio y de encuentro.
- **JULI**: equipos en terreno, en vivo por el WebSocket `/ws`, con aro rojo si falta la prueba
  de vida.

La URL de la API se elige, por orden, con `?api=` en la dirección (solo para esa pestaña; `?api=` vacío
lo desactiva) o con `VITE_API_URL` al compilar:

```bash
cd backend && uv run uvicorn app.main:app --port 8000
pnpm dev   # y abre http://localhost:5173/CATACLISMO/?api=http://localhost:8000
```

El backend debe permitir el origen del front en `CORS_ORIGINS` (por defecto, `localhost:5173`,
`localhost:4173` y GitHub Pages).
