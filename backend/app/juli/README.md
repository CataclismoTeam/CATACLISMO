# JULI — Guía completa para el desarrollador / agente de Frontend

Este directorio (`backend/app/juli/`) contiene el módulo **JULI**, independiente del pipeline `VALEN -> CATA -> LUCIA`, unificado para gestionar **equipos y operarios persistentes** y **tracking GPS/biométrico en tiempo real** sobre las zonas de incendio predichas por **CATA**.

---

## 1. Qué te vas a encontrar en esta carpeta

| Archivo | Qué hace |
| :--- | :--- |
| **`main.py`** | **Servidor FastAPI + WebSocket unificado**. Despliega 3 unidades tácticas (`unit-bombero-01`, `unit-paramedico-02`, `unit-dron-03`) directamente sobre el perímetro real del incendio de `cata_predictions.json`, emite updates cada 2 s por `WS /ws/tracking` y se sincroniza automáticamente con `juli_tracker` (`team_first_response_live`). |
| **`tracker.py`** | Gestor persistente en disco (`artifacts/state/juli_state.json`) y exportador GeoJSON `EPSG:4326` con equipos (`team_brif_huelva`, `team_ume_zamora`, `team_first_response_live`), centroides (`field_team_centroid`) y líneas de formación (`field_team_formation`). |
| **`config.py`** | Colores por estado/equipo, roles (`capataz`, `brigadista`, `conductor_autobomba`, `sanitario`, `observador`, `coordinador`) y rutas de artefactos. |
| **`requirements.txt`** | Dependencias mínimas (`fastapi`, `uvicorn[standard]`, `pydantic`) para levantar `main.py` de forma aislada. |
| **`artifacts/`** | Estado persistido (`artifacts/state/juli_state.json`) y GeoJSON pregenerado (`artifacts/geojson/juli_operators.geojson`). |

---

## 2. Cómo arrancarlo

Tiene **CORS abierto (`*`)** para todos los orígenes.

- **Opción A — Completo (VALEN/CATA/LUCIA + todo JULI)** desde `backend/`:
  ```bash
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  ```
- **Opción B — Standalone (solo JULI: simulador live + GeoJSON de equipos)** desde `backend/app/juli/`:
  ```bash
  pip install -r requirements.txt
  uvicorn main:app --reload --host 0.0.0.0 --port 8001
  ```

---

## 3. Endpoints de Simulación en Tiempo Real (Live Perimeter)

Disponibles tanto en `app.main` (`:8000`) como en `juli/main.py` (`:8001`):

- **`GET /api/units`**: Carga inicial del mapa. Devuelve un GeoJSON `FeatureCollection` (`features`) y el array plano `units` con: `id`, `role` (`paramédico` | `bombero` | `dron`), `lat`, `lon`, `status` (`activo` | `en_camino` | `sos`), `battery`, `heart_rate`.
- **`WS /ws/tracking`**: Emite el mismo payload actualizado cada **2 segundos** manteniendo a las unidades patrullando dentro de un radio operativo de `~1 km` alrededor del frente activo del incendio.
- **`POST /api/units/{unit_id}/sos`**: Fuerza en vivo el estado `"sos"` (`#EF4444`) de una unidad durante la demo (ej. `unit-bombero-01`).
- **`POST /api/units/sync-fire`**: Recalcula los anclajes sobre `cata_predictions.json` tras cambiar la fecha de simulación en CATA.

---

## 4. Endpoints de Equipos y Operarios Persistentes (`tracker.py`)

Disponibles en `app.main` (`:8000`) *(y los `GET` también en `:8001`)*:

- **`GET /api/juli/geojson`**: Devuelve el `FeatureCollection` completo (`EPSG:4326`) con coordenadas 3D `[lon, lat, elevation_m]` y tres tipos de `feature_type`:
  1. `field_operator` (`Point`): cada operario/unidad con `marker_color`, `team_color`, `role`, `status`, `battery_pct`, `heart_rate_bpm`, `callsign` y `assigned_task`.
  2. `field_team_centroid` (`Point`): centroide del equipo y resumen de efectivos.
  3. `field_team_formation` (`LineString`): línea táctica conectando a los miembros de cada equipo.
  - Filtros query opcionales: `?team_id=...`, `?status=...`, `?include_team_features=true|false`.
- **`GET /api/juli/teams`**: Lista estructurada de equipos y sus miembros.
- **`POST /api/juli/teams`**: Crea o actualiza un equipo (`team_id`, `name`, `code`, `sector`, `color`, `radio_channel`).
- **`POST /api/juli/operators`**: Añade o actualiza una persona dentro de un equipo (emite evento por `WS /ws`).
- **`PATCH /api/juli/operators/{operator_id}/location`**: Actualiza posición GPS/estado/batería en tiempo real (emite evento por `WS /ws`).
- **`DELETE /api/juli/operators/{operator_id}`**: Da de baja a un operario.

---

## 5. Ejemplo rápido en JavaScript Vanilla (para el Frontend)

```javascript
const API_BASE = "http://localhost:8001"; // o :8000 si usas app.main
const WS_URL = "ws://localhost:8001/ws/tracking";

async function loadInitialUnits() {
  const res = await fetch(`${API_BASE}/api/units`);
  const geojson = await res.json();
  // geojson.features (GeoJSON Point) y geojson.units (array limpio)
  renderUnitsOnMap(geojson);
}

function connectTrackingWS() {
  const ws = new WebSocket(WS_URL);
  ws.onmessage = (event) => renderUnitsOnMap(JSON.parse(event.data));
  ws.onclose = () => setTimeout(connectTrackingWS, 2000);
}

async function triggerSOS(unitId = "unit-bombero-01") {
  await fetch(`${API_BASE}/api/units/${unitId}/sos`, { method: "POST" });
}

function renderUnitsOnMap(geojson) {
  console.table(geojson.units);
}

loadInitialUnits().then(connectTrackingWS);
```
