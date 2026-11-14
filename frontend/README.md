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
