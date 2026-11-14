# Algoritmo LUCIA — Enrutamiento Seguro de Evacuación (TensorFlow 15 Canales + Open-Elevation + Puntos de Encuentro)

**LUCIA** (`ALGORITHM_NAME = "lucia"`) es el tercer eslabón de la arquitectura de **CATACLISMO**:

```
VALEN (Validación + Meteo/Lluvia/Vegetación + Carreteras OSM + Elevación Open-Elevation)
   └──► CATA (Predicción ConvLSTM 22 canales -> cata_predictions.json)
           └──► LUCIA (Modelo TensorFlow 15 canales + A* con Pendiente Δz y Puntos de Encuentro -> lucia_routes.geojson)
```

---

## 1. ¿Qué hace LUCIA?

Recibe el archivo de predicciones de **CATA** (`backend/app/cata/artifacts/predictions/cata_predictions.json`) más las capas de **Carreteras OSM** (`cell_roads.json`) y **Elevación Open-Elevation** (`cell_elevation.json`) de **VALEN**, y encuentra **el camino más corto y seguro hacia un Punto de Encuentro explícito (`meeting_point`)** tanto para **personas** (`profile="human"`) como para **animales / fauna** (`profile="animal"`), teniendo en cuenta:

1. **Zonas que se están quemando (`BURNING_ACTIVE`)**:
   - Celdas con fuego persistente (`state = 3` / `'B'`) o con ignición predicha por CATA (`state = 1` / `'P'`).
   - **Acción de LUCIA**: Bloqueo total intransitable (`passable = False`).
2. **Zonas ya quemadas (`ALREADY_BURNED`)**:
   - Celdas confirmadas por satélite que ya han ardido (`state = 2` / `'F'`).
   - **Acción de LUCIA**: Bloqueadas por defecto (`allow_already_burned = False`) debido a rescoldos, humo residual y caída de árboles.
3. **Zonas sin quemar (`SAFE`) con Threshold Seguro al Fuego (`SAFE_FIRE_THRESHOLD = 0.25`)**:
   - Si `fire_probability_t1 >= safe_fire_threshold`: se clasifican como `THRESHOLD_BUFFER_UNSAFE` y **se bloquean**.
   - Si `fire_probability_t1 < safe_fire_threshold`: se clasifican como `SAFE_UNBURNED` y son **transitables**.
4. **Cambios de elevación direccionales ($\Delta z$) con Open-Elevation (`VALEN`)**:
   - En cada paso A\* `(r, c) -> (nr, nc)`, LUCIA calcula $\Delta z = z_{nr,nc} - z_{r,c}$ (en metros) y aplica la **función de marcha de Tobler** (`compute_slope_cost_multiplier`), penalizando subidas y bajadas pronunciadas.
   - Aplica además una **penalización convectiva de efecto chimenea** cuando una transición sube cuesta arriba ($\Delta z > 5\text{ m}$) cerca de un frente de fuego activo.
   - Todas las geometrías GeoJSON exportan coordenadas **3D `[lon, lat, elevation_m]`** y el perfil longitudinal de elevación (`elevation_profile_m`, `total_ascent_m`, `total_descent_m`, `max_slope_pct`).
5. **Puntos de Encuentro Explícitos (`meeting_points`)**:
   - Cada ruta tiene una **finalidad explícita**: llegar a un **Punto de Encuentro (`meeting_point`)** con nombre, ID, altitud, acceso viario y capacidad (`target_meeting_point_id`, `target_meeting_point_name`, `target_meeting_point_kind`).
   - Soporta tanto **Puntos de Encuentro oficiales autodesignados** en zonas llanas conectadas a carreteras seguras como **Puntos de Encuentro personalizados** enviados en `POST /api/lucia/route`.

---

## 2. Arquitectura del Modelo Modular de TensorFlow (`model.py`)

**LUCIA** cuenta con una red neuronal modular en TensorFlow/Keras (`lucia_router_c15`) con soporte de **Channel Surgery** (`expand_lucia_channels` / `transfer_lucia_weights`):

- **Entrada `(H, W, 15)`** (`LUCIA_CHANNEL_REGISTRY`):
  - `0: is_safe_unburned`
  - `1: is_burning_active`
  - `2: is_already_burned`
  - `3: fire_probability_t1`
  - `4: fire_proximity_risk`
  - `5: arrival_urgency`
  - `6: human_base_cost_norm`
  - `7: animal_base_cost_norm`
  - `8: veg_flammability` (VALEN: WorldCover + IFN3)
  - `9: meteo_wind_speed` (VALEN: Meteomatics)
  - `10: meteo_fwi_temp` (VALEN: FWI + Temperatura)
  - `11: border_escape_affinity`
  - `12: road_access` (VALEN: carreteras y caminos OpenStreetMap)
  - `13: elevation_norm` (VALEN: altitud normalizada Open-Elevation)
  - `14: slope_steepness` (VALEN: pendiente topográfica entre celdas vecinas)
- **Salida `(H, W, 3)` (`sigmoid`)**:
  - Canal `0`: `human_risk_field` $\in [0, 1]$
  - Canal `1`: `animal_risk_field` $\in [0, 1]$
  - Canal `2`: `safe_haven_score` $\in [0, 1]$

---

## 3. Estructura de Archivos

- `backend/app/lucia/config.py`: Constantes, umbrales (`SAFE_FIRE_THRESHOLD = 0.25`), registro de 15 canales y rutas.
- `backend/app/lucia/model.py`: Red neuronal TensorFlow/Keras + *channel surgery* (`expand_lucia_channels`) + extractor de 15 canales (incluyendo OSM y Open-Elevation de VALEN).
- `backend/app/lucia/router.py`: Proyección geodésica exacta EPSG:3035 $\leftrightarrow$ WGS84, gestor de Puntos de Encuentro (`resolve_zone_meeting_points`), buscador A\* espacio-temporal con coste de pendiente de Tobler ($\Delta z$) y exportador GeoJSON 3D.
- `backend/app/lucia/train.py`: CLI para entrenar (`--mode train`), expandir canales (`--mode expand`) o generar rutas (`--mode route`).
- `backend/app/lucia/FRONTEND_AI_HANDOFF.md`: Guía técnica específica para el agente de IA de Frontend.
- `backend/app/lucia/artifacts/models/lucia_c15.keras`: Modelo TensorFlow entrenado (15 canales).
- `backend/app/lucia/artifacts/routes/lucia_routes.geojson`: Archivo GeoJSON (WGS84 3D) con las rutas, perfiles de elevación y Puntos de Encuentro.
