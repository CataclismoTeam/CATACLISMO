# Backend de CATACLISMO (`VALEN -> CATA -> LUCIA` + `JULI` + `NRT Live`)

Documentación operativa del backend en Python (`FastAPI` + `TensorFlow/Keras` + GeoJSON `EPSG:4326`).

---

## 1. Arquitectura de Módulos

| Módulo | Ruta | Función principal |
| :--- | :--- | :--- |
| **VALEN** | `app/valen/` | Ingesta FIRMS, proyección a rejilla `1 km × 1 km` (`EPSG:3035`), agregación `cell_6h` / `cell_day` y enriquecimiento (Open-Meteo, NASA POWER, CORINE, OSM, Open-Elevation). |
| **CATA** | `app/cata/` | Modelo `ConvLSTM2D` (`cata_c22.keras`) en pasos tácticos de **6 horas** (`5 × 6h = 30h`). Exporta `cata_predictions.json` con soporte de fecha (`--date`). |
| **LUCIA** | `app/lucia/` | Modelo `lucia_c15.keras` + enrutamiento A\* con pendientes $\Delta z$ (Tobler) y red viaria OSM. Genera `lucia_routes.geojson` para personas, animales y Puntos de Encuentro. |
| **CONTINUAL** | `app/continual/` | Aprendizaje continuo recursivo (calibración EMA por bloque + *replay buffer* + micro-pasos solo en cabeza) sin necesidad de reentrenar CATA ni LUCIA. |
| **LIVE NRT** | `app/live_nrt.py` | Feed en tiempo casi real desde **NASA FIRMS NRT** + **Open-Meteo** $\rightarrow$ `VALEN 6h` $\rightarrow$ `CATA` $\rightarrow$ `LUCIA`. |
| **JULI** | `app/juli/` | Sistema independiente de seguimiento en tiempo real (`REST` + `WS /ws/tracking` + GeoJSON) de equipos y First Responders desplegados sobre el perímetro del incendio. |

---

## 2. Secretos y Variables de Entorno (`FIRMS_MAP_KEY`)

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

## 3. Comandos Rápidos (desde `backend/`)

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
- **JULI (Live & Equipos):** `GET /api/units`, `POST /api/units/{unit_id}/sos`, `POST /api/units/sync-fire`, `WS /ws/tracking`, `GET /api/juli/geojson`, `GET /api/juli/teams`
