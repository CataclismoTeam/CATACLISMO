# Backend de CATACLISMO (`VALEN -> CATA -> LUCIA` + `JULI` + `NRT Live`)

Documentación operativa del backend en Python (`FastAPI` + `TensorFlow/Keras` + GeoJSON `EPSG:4326`).

---

## 1. Arquitectura de Módulos

| Módulo | Ruta | Función principal |
| :--- | :--- | :--- |
| **VALEN** | `app/valen/` | Ingesta FIRMS, proyección a cuadrícula estándar `1000 × 1000 m` (`EPSG:3035`, `ES1K`), agregación `cell_6h` / `cell_day` y enriquecimiento (Open-Meteo, NASA POWER, CORINE, OSM, Open-Elevation). |
| **CATA** | `app/cata/` | Modelo `ConvLSTM2D` (`cata_c22.keras`) sobre cuadrantes `1000 × 1000 m` en pasos tácticos de **6 horas** (`5 × 6h = 30h`). Exporta `cata_predictions.json` con soporte de fecha (`--date`). |
| **LUCIA** | `app/lucia/` | Modelo `lucia_c15.keras` + enrutamiento A\* por cuadrantes `1000 × 1000 m` con pendientes $\Delta z$ (Tobler) y red viaria OSM. Genera `lucia_routes.geojson` para personas, animales y Puntos de Encuentro. |
| **CONTINUAL** | `app/continual/` | Aprendizaje continuo recursivo (calibración EMA por bloque + *replay buffer* + micro-pasos solo en cabeza) sin necesidad de reentrenar CATA ni LUCIA. |
| **LIVE NRT** | `app/live_nrt.py` | Feed en tiempo casi real desde **NASA FIRMS NRT** + **Open-Meteo** $\rightarrow$ `VALEN 6h` $\rightarrow$ `CATA` $\rightarrow$ `LUCIA`. |
| **JULI** | `app/juli/` | Sistema independiente de seguimiento en tiempo real (`REST` + `WS /ws/tracking` + GeoJSON) con sistema dual: **cuadrante `1000 × 1000 m` (`ES1K`) + subcoordenadas locales + coordenadas absolutas (`WGS84`/`EPSG:3035`)**. |

---

## 2. Cuadrícula Táctica Unificada (`1000 × 1000 m`)

Todo el backend opera de forma normalizada sobre **una única cuadrícula de cuadrantes de `1000 × 1000 m` (`1 km²`)**:

- **Sistema de referencia espacial de rejilla:** `EPSG:3035` (`ETRS89-LAEA Europe`, metros) — implementado sin dependencias C en [`app/valen/laea.py`](app/valen/laea.py).
- **Estándar del cuadrante (Nivel base `L0`):**
  - Tamaño fijo: **`1000 × 1000 m`** (`CELL_SIZE_M = 1000.0`, `CHUNK_SIZE_M = 1000.0`).
  - Prefijo e identificador canónico: **`ES1K:L0:Y{iy:05d}:X{ix:05d}`** (`ix = floor(x_3035 / 1000)`, `iy = floor(y_3035 / 1000)`).
  - Centroide del cuadrante: `((ix + 0.5) * 1000.0, (iy + 0.5) * 1000.0)` convertido a `WGS84` (`EPSG:4326`) para todas las respuestas GeoJSON/API.
- **Compatibilidad transversal garantizada:**
  - **VALEN / Live NRT / CATA / LUCIA** comparten exactamente los mismos índices `(iy, ix)` y `cell_id` (`ES1K:L0:...`). Además, `POST /api/lucia/route` y los `custom_meeting_points` aceptan tanto `(lon, lat)` como `quadrant_id` / `cell_id` de `1000 × 1000 m`.
  - **JULI** sitúa cada operario y equipo tanto por **coordenadas absolutas** (`lon`, `lat`, `epsg3035_x_m`, `epsg3035_y_m`) como por su **cuadrante `1000 × 1000 m`** (`quadrant_id`) y **subcoordenadas internas** (`offset_x_m`, `offset_y_m` $\in [0, 1000)\text{ m}$, `sub_x_norm`/`sub_y_norm` $\in [0, 1)$, subrejilla `sub_100m_rc`, subcelda de `10 m` `sub_10m_rc` y `sub_cell_id`).

---

## 3. Secretos y Variables de Entorno (`FIRMS_MAP_KEY`)

> [!IMPORTANT]
> La clave de la API de NASA FIRMS (**`FIRMS_MAP_KEY`**) se encuentra guardada en los **secretos del repositorio de GitHub** (`Settings -> Secrets and variables -> Actions -> FIRMS_MAP_KEY`).
>
> **Nunca** la subas en texto plano al repositorio ni la commitees.

- **En GitHub Actions / CI / Workflows:** se inyecta automáticamente mediante `${{ secrets.FIRMS_MAP_KEY }}`.
- **En desarrollo local:** créate un archivo `backend/.env` (ya ignorado por `.gitignore`) con:
  ```env
  FIRMS_MAP_KEY=tu_clave_de_los_secretos_del_repo
  ```

---

## 4. Comandos Rápidos (desde `backend/`)

### Levantar el servidor FastAPI completo
```bash
.venv/bin/pip install -r app/juli/requirements.txt   # solo la primera vez si falta fastapi/uvicorn
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Feed de datos en directo (NASA FIRMS NRT + Open-Meteo)
- **Por consola:**
  ```bash
  .venv/bin/python -m app.live_nrt --days 2
  ```
- **Por API REST:**
  - `POST /api/live/refresh?days=2` — Descarga detecciones NRT de la Península Ibérica, predice con CATA y actualiza las rutas de LUCIA.
  - `GET /api/live/status` — Estado de la última ingesta NRT.

### Simular cualquier fecha histórica en turnos de 6h (`00:00`, `06:00`, `12:00`, `18:00`)
```bash
.venv/bin/python -m app.cata.train --mode predict --date "2022-07-18 12:00"
.venv/bin/python -m app.lucia.train --mode route
```

### Endpoints principales para el Frontend
- **LUCIA / CATA:** `GET /api/lucia/routes`, `POST /api/lucia/route`, `GET /api/lucia/meeting-points`, `GET /api/cata/predictions`
- **Aprendizaje Continuo:** `GET /api/continual/status`, `POST /api/continual/feedback`
- **JULI (Live, Equipos, Prueba de Vida, Chat E2EE & Radio BLE/TETRA PEI):** `GET /api/units`, `POST /api/units/{unit_id}/sos`, `POST /api/units/sync-fire`, `WS /ws/tracking`, `GET /api/juli/geojson`, `GET /api/juli/teams`, `GET /api/juli/proof-of-life`, `POST /api/juli/operators/{operator_id}/proof-of-life`, `POST /api/juli/proof-of-life/check` (`WS /ws` emite `proof_of_life_alert` a **Central** y al **escuadrón** si un operario lleva ≥ 15 min inmóvil o su cuadrante `1000 × 1000 m` está ardiendo, destacando `last_location`), chat táctico **E2EE** (`WS /ws/chat`, `/api/juli/chat/*`), y enlace walkie-talkie **BLE GATT + TETRA PEI (`ETSI TS 100 392-5`)** (`/api/juli/radio/*`, `WS /ws/radio`) con simulación y cambio atómico de frecuencia/escuadrón.
